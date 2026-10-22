"""Smoke tests for the FocusOS focus engine."""

import ctypes
import json
import os
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest
from fastapi import HTTPException
import main as focusos_main

from api.focus_api import FocusAPI
from config.settings import (
    AUTO_OPTIMIZE_USER_PROCESSES,
    AUTO_SUSPEND_DELAY_SECONDS,
    CLEANUP_AUTO_MIN_AGE_SECONDS,
    RESOURCE_PROFILES,
)
from core import elevation, gnome_focus, process_manager as process_manager_module
from core.focus_engine import FocusEngine
from core.focus_runtime import FocusRuntime
from core.platform_support import is_windows
from core.process_manager import ProcessManager
from core.resource_manager import ResourceManager
from core.storage_manager import StorageManager
from core.system_monitor import SystemMonitor
from dashboard.main_window import MainWindow
from dashboard.desktop_app import HISTORY_LIMIT, MetricHistory
from main import configure_auto_ram_management, review_and_clean_folder


class FakeMonitor:
    def __init__(self):
        self.calls = 0

    def collect(self):
        self.calls += 1
        return {
            "cpu_usage": 31.5,
            "ram_usage": 42.0,
            "gpu_usage": None,
            "active_window": {"application": "Code.exe", "title": "project.py - VS Code", "pid": 12},
            "processes": [
                {"pid": 12, "name": "Code.exe", "cpu_percent": 10.0, "memory_rss": 50 * 1024 * 1024},
                {"pid": 20, "name": "chrome.exe", "cpu_percent": 2.0, "memory_rss": 100 * 1024 * 1024},
            ],
        }


class ManagedFakeProcess:
    def __init__(self, pid, name, username):
        self.pid = pid
        self._name = name
        self._username = username
        self._suspend_calls = 0
        self._resume_calls = 0
        self._priority = 0

    def create_time(self):
        return 123.0

    def username(self):
        return self._username

    def name(self):
        return self._name

    def suspend(self):
        self._suspend_calls += 1

    def resume(self):
        self._resume_calls += 1

    def is_running(self):
        return True

    def nice(self, priority=None):
        if priority is not None:
            self._priority = priority
        return self._priority


def test_system_monitor_skips_processes_that_exit_during_collection(monkeypatch):
    class FakeProcess:
        def __init__(self, pid, name, cpu_percent):
            self.info = {"pid": pid, "name": name, "ppid": 0, "create_time": 123.0}
            self._cpu_percent = cpu_percent

        def cpu_percent(self, interval=None):
            if isinstance(self._cpu_percent, Exception):
                raise self._cpu_percent
            return self._cpu_percent

        def memory_percent(self):
            return 2.0

        def memory_info(self):
            return type("MemoryInfo", (), {"rss": 12 * 1024 * 1024})()

        def io_counters(self):
            return type("IOCounters", (), {"read_bytes": 10, "write_bytes": 20})()

    monkeypatch.setattr(
        SystemMonitor,
        "_get_active_window",
        staticmethod(lambda: {"application": "Code.exe", "title": "project.py", "pid": 1}),
    )
    monkeypatch.setattr(
        psutil,
        "process_iter",
        lambda attrs: [
            FakeProcess(1, "Code.exe", 12.5),
            FakeProcess(2, "exited.exe", psutil.NoSuchProcess(2, "exited.exe")),
        ],
    )
    monkeypatch.setattr(psutil, "cpu_percent", lambda interval=None: 20.0)
    monkeypatch.setattr(
        psutil,
        "virtual_memory",
        lambda: type(
            "Memory",
            (),
            {"percent": 50.0, "available": 1024, "total": 4096},
        )(),
    )
    monkeypatch.setattr(
        psutil,
        "disk_usage",
        lambda path: type("Disk", (), {"percent": 44.0, "free": 2048, "total": 8192})(),
    )

    metrics = SystemMonitor().collect()

    assert len(metrics["processes"]) == 1
    assert metrics["processes"][0]["pid"] == 1
    assert metrics["processes"][0]["cpu_percent"] == 12.5
    assert metrics["processes"][0]["memory_percent"] == 2.0
    assert metrics["processes"][0]["memory_rss"] == 12 * 1024 * 1024
    assert metrics["processes"][0]["read_bytes"] == 10
    assert metrics["processes"][0]["write_bytes"] == 20
    assert metrics["disk_usage"] == 44.0
    assert metrics["disk_free_bytes"] == 2048
    assert metrics["ram_available_bytes"] == 1024


def test_system_monitor_averages_gpu_utilization_when_nvidia_smi_is_available(monkeypatch):
    monkeypatch.setattr("core.system_monitor.shutil.which", lambda name: "nvidia-smi")
    monkeypatch.setattr(
        "core.system_monitor.subprocess.run",
        lambda *args, **kwargs: type("Result", (), {"stdout": "20\n40\n"})(),
    )

    assert SystemMonitor._get_gpu_usage() == 30.0


def test_process_manager_suspends_and_restores_allowlisted_process_after_delay(monkeypatch):
    monkeypatch.setattr("core.process_manager.is_windows", lambda: True)
    now = [0.0]
    username = psutil.Process().username()
    process = ManagedFakeProcess(50000, "Editor.exe", username)
    manager = ProcessManager(
        allowlist=("Editor.exe",),
        suspend_after_seconds=300,
        clock=lambda: now[0],
        process_factory=lambda pid: process,
    )
    process_info = {
        "pid": 50000,
        "name": "Editor.exe",
        "create_time": 123.0,
        "cpu_percent": 1.0,
    }

    first = manager.build_priority_plan([process_info], focus_pid=None)
    assert first[0]["suspended"] is False

    now[0] = 300.0
    background = manager.build_priority_plan([process_info], focus_pid=None)
    assert background[0]["suspended"] is True
    assert process._suspend_calls == 1

    focused = manager.build_priority_plan([process_info], focus_pid=50000)
    assert focused[0]["suspended"] is False
    assert process._resume_calls == 1
    assert process.nice() == psutil.HIGH_PRIORITY_CLASS

    assert manager.restore_all() == []
    assert process.nice() == 0


def test_configured_process_suspension_delay_is_two_minutes():
    runtime = FocusRuntime(monitor=FakeMonitor())

    assert AUTO_SUSPEND_DELAY_SECONDS == 120
    assert runtime.process_manager.suspend_after_seconds == 120


def test_resource_profiles_update_policy_thresholds_and_restore_managed_settings():
    class ProfileProcessManager:
        auto_optimize_user_processes = False
        suspend_after_seconds = AUTO_SUSPEND_DELAY_SECONDS
        suspended_count = 0
        working_set_trimmed_bytes = 0
        action_errors = []

        def __init__(self):
            self.restore_calls = 0

        def restore_all(self):
            self.restore_calls += 1
            return []

        def build_priority_plan(self, processes, focus_pid, apply_controls=True):
            return []

    process_manager = ProfileProcessManager()
    runtime = FocusRuntime(
        monitor=FakeMonitor(),
        process_manager=process_manager,
    )
    runtime.start()

    focus_state = runtime.set_resource_profile("focus")
    assert focus_state["resource_profile"] == "focus"
    assert process_manager.suspend_after_seconds == 60
    assert runtime.resource_manager.assess(70, 0, 0)["status"] == "WARNING"

    performance_state = runtime.set_resource_profile("performance")
    assert performance_state["resource_profile"] == "performance"
    assert process_manager.suspend_after_seconds == 300
    assert runtime.resource_manager.assess(89, 89, 94)["status"] == "NORMAL"
    assert process_manager.restore_calls == 2

    balanced_state = runtime.set_resource_profile("balanced")
    assert balanced_state["resource_profile"] == "balanced"
    assert process_manager.suspend_after_seconds == AUTO_SUSPEND_DELAY_SECONDS
    assert runtime.resource_manager.assess(80, 0, 0)["status"] == "WARNING"


def test_resource_profile_thresholds_are_validated():
    manager = ResourceManager()

    with pytest.raises(ValueError, match="between 0 and 100"):
        manager.set_warning_thresholds(101, 85, 90)


def test_unknown_resource_profile_is_rejected():
    runtime = FocusRuntime(monitor=FakeMonitor())

    with pytest.raises(ValueError, match="Unknown resource profile"):
        runtime.set_resource_profile("turbo")

    assert set(RESOURCE_PROFILES) == {"focus", "balanced", "performance"}


def test_focus_engine_detects_specific_browser_tabs():
    engine = FocusEngine()

    assert engine.classify_task("chrome.exe", "swap1930/FocusOS · Pull requests · GitHub") == "coding"
    assert engine.classify_task("msedge.exe", "Two Sum - LeetCode") == "coding"
    assert engine.classify_task("firefox.exe", "Python AsyncIO - Stack Overflow") == "coding"
    assert engine.classify_task("chrome.exe", "train_model.ipynb - Google Colab") == "ml_training"
    assert engine.classify_task("chrome.exe", "ChatGPT - OpenAI") == "ml_training"
    assert engine.classify_task("chrome.exe", "Google Meet - Team Sync") == "communication"
    assert engine.classify_task("chrome.exe", "Figma - Mobile UI Prototype") == "rendering"
    assert engine.classify_task("chrome.exe", "Google Docs - Q3 Roadmap") == "presentation"
    assert engine.classify_task("chrome.exe", "lofi hip hop radio - YouTube") == "browsing"
    assert engine.classify_task("chrome.exe", "New Tab") == "browsing"


def test_runtime_automatically_switches_profile_based_on_tab_and_app():
    class DynamicTabMonitor:
        def __init__(self):
            self.active_window = {"application": "chrome.exe", "title": "GitHub - swap1930/FocusOS", "pid": 100}

        def collect(self):
            return {
                "cpu_usage": 20.0,
                "ram_usage": 30.0,
                "gpu_usage": None,
                "active_window": self.active_window,
                "processes": [
                    {"pid": 100, "name": "chrome.exe", "cpu_percent": 10.0, "memory_rss": 50 * 1024 * 1024},
                ],
            }

    class SimpleProcessManager:
        auto_optimize_user_processes = False
        suspend_after_seconds = AUTO_SUSPEND_DELAY_SECONDS
        suspended_count = 0
        working_set_trimmed_bytes = 0
        action_errors = []

        def build_priority_plan(self, processes, focus_pid, apply_controls=True):
            return []

        def restore_all(self):
            return []

    monitor = DynamicTabMonitor()
    process_manager = SimpleProcessManager()
    runtime = FocusRuntime(monitor=monitor, process_manager=process_manager)

    # 1. On GitHub tab in Chrome -> automatically sets "focus" profile (60s suspend delay)
    state = runtime.start()
    assert state["focus_mode"] == "coding"
    assert state["resource_profile"] == "focus"
    assert process_manager.suspend_after_seconds == 60
    assert runtime.resource_manager.assess(70, 0, 0)["status"] == "WARNING"

    # 2. Switch to Figma (design/rendering) tab -> automatically sets "performance" profile (300s suspend delay)
    monitor.active_window = {"application": "chrome.exe", "title": "Figma - App Mockup", "pid": 100}
    state = runtime.refresh()
    assert state["focus_mode"] == "rendering"
    assert state["resource_profile"] == "performance"
    assert process_manager.suspend_after_seconds == 300
    assert runtime.resource_manager.assess(80, 80, 90)["status"] == "NORMAL"

    # 3. Switch to YouTube (general browsing/media) tab -> automatically sets "balanced" profile (120s delay)
    monitor.active_window = {"application": "chrome.exe", "title": "YouTube - Music Video", "pid": 100}
    state = runtime.refresh()
    assert state["focus_mode"] == "browsing"
    assert state["resource_profile"] == "balanced"
    assert process_manager.suspend_after_seconds == AUTO_SUSPEND_DELAY_SECONDS
    assert runtime.resource_manager.assess(80, 0, 0)["status"] == "WARNING"

    # 4. Manual override locks profile; re-enabling auto restores dynamic tuning
    runtime.set_resource_profile("focus")
    assert runtime.state.resource_profile == "focus"
    assert not runtime.state.auto_resource_profile

    # While locked, refresh with YouTube does not override the manual choice
    state = runtime.refresh()
    assert state["resource_profile"] == "focus"

    # Re-enabling auto resumes dynamic tuning
    runtime.enable_auto_resource_profile()
    state = runtime.refresh()
    assert state["resource_profile"] == "balanced"
    assert state["auto_resource_profile"]


def test_main_launches_desktop_dashboard_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr("sys.argv", ["main.py"])
    monkeypatch.setattr(
        focusos_main,
        "run_desktop_dashboard",
        lambda: calls.append("desktop"),
    )

    focusos_main.main()

    assert calls == ["desktop"]


def test_dashboard_metric_history_is_bounded_and_records_resource_values():
    history = MetricHistory()
    state = {
        "cpu_usage": 21.5,
        "ram_usage": 63.0,
        "disk_usage": 44.0,
        "gpu_usage": 81.0,
        "active_processes": 3,
        "background_processes": 8,
        "suspended_processes": 1,
    }

    for _ in range(HISTORY_LIMIT + 1):
        history.record(state)

    assert len(history.samples) == HISTORY_LIMIT
    assert history.samples[-1]["CPU %"] == 21.5
    assert history.samples[-1]["GPU %"] == 81.0
    assert history.samples[-1]["Background"] == 8


def test_selected_background_process_is_auto_suspended_after_two_minutes_and_restored(monkeypatch):
    monkeypatch.setattr("core.process_manager.is_windows", lambda: True)
    now = [0.0]
    username = psutil.Process().username()
    process = ManagedFakeProcess(50006, "Editor.exe", username)
    active_pid = [10]
    trim_calls = []
    manager = ProcessManager(
        suspend_after_seconds=AUTO_SUSPEND_DELAY_SECONDS,
        clock=lambda: now[0],
        process_factory=lambda pid: process,
        active_pid_provider=lambda: active_pid[0],
        selected_instances={(50006, 123.0)},
        working_set_trimmer=lambda pid: (trim_calls.append(pid) or 25 * 1024 * 1024, None),
    )
    process_info = {
        "pid": 50006,
        "name": "Editor.exe",
        "create_time": 123.0,
        "cpu_percent": 1.0,
        "memory_rss": 300 * 1024 * 1024,
    }

    assert manager.build_priority_plan([process_info], focus_pid=10)[0]["suspended"] is False
    now[0] = 119.0
    assert manager.build_priority_plan([process_info], focus_pid=10)[0]["suspended"] is False
    now[0] = 120.0
    suspended = manager.build_priority_plan([process_info], focus_pid=10)
    assert suspended[0]["suspended"] is True
    assert process._suspend_calls == 1
    assert trim_calls == [50006]
    assert manager.working_set_trimmed_bytes == 25 * 1024 * 1024

    active_pid[0] = 50006
    resumed = manager.build_priority_plan([process_info], focus_pid=50006)
    assert resumed[0]["suspended"] is False
    assert process._resume_calls == 1
    assert process.nice() == psutil.HIGH_PRIORITY_CLASS

    manager.restore_all()
    assert process.nice() == 0

def test_auto_ram_startup_enables_only_explicitly_confirmed_processes(monkeypatch):
    username = psutil.Process().username()
    process = ManagedFakeProcess(50007, "Editor.exe", username)
    manager = ProcessManager(
        process_factory=lambda pid: process,
        active_pid_provider=lambda: 10,
    )
    runtime = type(
        "Runtime",
        (),
        {
            "process_manager": manager,
            "monitor": type(
                "Monitor",
                (),
                {"get_active_window_pid": lambda self: 10},
            )(),
        },
    )()
    monkeypatch.setattr(
        "main.api",
        type("API", (), {"runtime": runtime})(),
    )
    responses = iter(["1", "AUTO SUSPEND"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))
    state = {
        "priority_plan": [
            {
                "pid": 50007,
                "name": "Editor.exe",
                "create_time": 123.0,
                "memory_rss": 250 * 1024 * 1024,
            }
        ]
    }

    configure_auto_ram_management(state)

    assert manager.selected_instances == {(50007, 123.0)}


@pytest.mark.parametrize("skip_disk_review", [False, True])
def test_normal_startup_runs_integrated_cleanup_monitoring_and_ram_setup(
    monkeypatch,
    skip_disk_review,
):
    events = []

    class Runtime:
        state = type("State", (), {"status": "STOPPED"})()
        process_manager = type(
            "Manager",
            (),
            {
                "allowlist": set(),
                "selected_process_count": 0,
                "auto_optimize_user_processes": False,
            },
        )()

        def start(self):
            events.append("monitor-start")

        def snapshot(self):
            return {"priority_plan": []}

        def get_state(self):
            return {
                "status": "RUNNING",
                "ram_available_bytes": 0,
                "disk_free_bytes": 0,
                "top_memory_processes": [],
                "resource_status": "NORMAL",
                "resource_warnings": [],
                "process_action_errors": [],
                "working_set_trimmed_bytes": 0,
                "focus_application": None,
                "focus_window": None,
                "focus_mode": "idle",
                "focus_score": 0,
                "cpu_usage": 0,
                "ram_usage": 0,
                "disk_usage": 0,
                "gpu_usage": None,
                "active_processes": 0,
                "background_processes": 0,
                "suspended_processes": 0,
            }

        def stop(self):
            events.append("monitor-stop")
            return {"process_action_errors": []}

    class API:
        runtime = Runtime()

        def get_state(self):
            return self.runtime.get_state()

    monkeypatch.setattr(
        focusos_main,
        "api",
        API(),
    )
    monkeypatch.setattr(
        focusos_main,
        "optimize_disk",
        lambda: events.append("disk-review"),
    )
    monkeypatch.setattr(
        focusos_main,
        "configure_auto_ram_management",
        lambda state: events.append("ram-setup"),
    )

    def interrupt(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(focusos_main.time, "sleep", interrupt)
    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--terminal"]
        + (["--skip-disk-review"] if skip_disk_review else []),
    )

    focusos_main.main()

    if skip_disk_review:
        assert "disk-review" not in events
        assert events[:2] == ["monitor-start", "ram-setup"]
    else:
        assert events.index("disk-review") < events.index("monitor-start")
        assert events.index("monitor-start") < events.index("ram-setup")


def test_process_manager_does_not_change_unallowlisted_process():
    username = psutil.Process().username()
    process = ManagedFakeProcess(50001, "Editor.exe", username)
    manager = ProcessManager(
        allowlist=(),
        suspend_after_seconds=0,
        process_factory=lambda pid: process,
    )
    process_info = {
        "pid": 50001,
        "name": "Editor.exe",
        "create_time": 123.0,
        "cpu_percent": 1.0,
    }

    plan = manager.build_priority_plan([process_info], focus_pid=None)

    assert plan[0]["suspended"] is False
    assert process._suspend_calls == 0
    assert process.nice() == 0


def test_auto_optimization_prioritizes_focus_and_trims_eligible_background_apps(monkeypatch):
    monkeypatch.setattr("core.process_manager.is_windows", lambda: True)
    now = [0.0]
    active_pid = [50010]
    username = psutil.Process().username()
    focused = ManagedFakeProcess(50010, "Editor.exe", username)
    background = ManagedFakeProcess(50011, "Browser.exe", username)
    protected = ManagedFakeProcess(50012, "svchost.exe", username)
    processes = {50010: focused, 50011: background, 50012: protected}
    trim_calls = []
    manager = ProcessManager(
        suspend_after_seconds=120,
        clock=lambda: now[0],
        process_factory=lambda pid: processes[pid],
        active_pid_provider=lambda: active_pid[0],
        working_set_trimmer=lambda pid: (
            trim_calls.append(pid) or (16 * 1024 * 1024, None)
        ),
    )
    manager.auto_optimize_user_processes = True
    process_info = [
        {"pid": 50010, "name": "Editor.exe", "create_time": 123.0},
        {"pid": 50011, "name": "Browser.exe", "create_time": 123.0},
        {"pid": 50012, "name": "svchost.exe", "create_time": 123.0},
    ]

    manager.build_priority_plan(process_info, focus_pid=50010)
    assert focused.nice() == psutil.ABOVE_NORMAL_PRIORITY_CLASS
    assert background.nice() == psutil.BELOW_NORMAL_PRIORITY_CLASS
    assert protected.nice() == 0

    now[0] = 120.0
    plan = manager.build_priority_plan(process_info, focus_pid=50010)
    assert trim_calls == [50011]
    assert manager.working_set_trimmed_bytes == 16 * 1024 * 1024
    assert next(row for row in plan if row["pid"] == 50011)["suspended"] is False

    active_pid[0] = 50011
    manager.build_priority_plan(process_info, focus_pid=50011)
    assert focused.nice() == psutil.BELOW_NORMAL_PRIORITY_CLASS
    assert background.nice() == psutil.ABOVE_NORMAL_PRIORITY_CLASS

    manager.restore_all()
    assert focused.nice() == 0
    assert background.nice() == 0
    monkeypatch.undo()


def test_focus_runtime_enables_configured_automatic_optimization():
    runtime = FocusRuntime(monitor=FakeMonitor())

    assert AUTO_OPTIMIZE_USER_PROCESSES is True
    assert runtime.process_manager.auto_optimize_user_processes is is_windows()


def test_focus_runtime_enables_supported_optimization_on_linux(monkeypatch):
    monkeypatch.setattr("core.focus_runtime.is_windows", lambda: False)
    monkeypatch.setattr("core.focus_runtime.is_linux", lambda: True)

    runtime = FocusRuntime(monitor=FakeMonitor())

    assert runtime.platform == "Linux"
    assert runtime.process_manager.auto_optimize_user_processes is True


def test_linux_auto_optimization_batches_background_and_restores_foreground(monkeypatch):
    monkeypatch.setattr("core.process_manager.is_windows", lambda: False)
    monkeypatch.setattr("core.process_manager.is_linux", lambda: True)
    monkeypatch.setattr(os, "SCHED_OTHER", 0, raising=False)
    monkeypatch.setattr(os, "SCHED_BATCH", 3, raising=False)
    now = [0.0]
    active_pid = [50020]
    username = psutil.Process().username()
    focused = ManagedFakeProcess(50020, "editor", username)
    background = ManagedFakeProcess(50021, "browser", username)
    processes = {50020: focused, 50021: background}
    policies = {50020: 0, 50021: 0}
    scheduler_calls = []

    def set_scheduler(pid, policy, parameter):
        policies[pid] = policy
        scheduler_calls.append((pid, policy))

    monkeypatch.setattr(os, "sched_getscheduler", lambda pid: policies[pid], raising=False)
    monkeypatch.setattr(
        os,
        "sched_getparam",
        lambda pid: SimpleNamespace(sched_priority=0),
        raising=False,
    )
    monkeypatch.setattr(os, "sched_setscheduler", set_scheduler, raising=False)
    monkeypatch.setattr(os, "sched_param", lambda priority: SimpleNamespace(sched_priority=priority), raising=False)
    trim_calls = []
    manager = ProcessManager(
        suspend_after_seconds=120,
        clock=lambda: now[0],
        process_factory=lambda pid: processes[pid],
        active_pid_provider=lambda: active_pid[0],
        working_set_trimmer=lambda pid: (
            trim_calls.append(pid) or (4 * 1024 * 1024, None)
        ),
    )
    manager.auto_optimize_user_processes = True
    process_info = [
        {"pid": 50020, "name": "editor", "create_time": 123.0},
        {"pid": 50021, "name": "browser", "create_time": 123.0},
    ]

    manager.build_priority_plan(process_info, focus_pid=50020)
    assert policies == {50020: 0, 50021: 3}
    now[0] = 120.0
    manager.build_priority_plan(process_info, focus_pid=50020)
    assert trim_calls == [50021]
    assert manager.working_set_trimmed_bytes == 4 * 1024 * 1024

    active_pid[0] = 50021
    manager.build_priority_plan(process_info, focus_pid=50021)
    assert policies[50021] == 0
    assert (50021, 0) in scheduler_calls
    assert manager.restore_all() == []


def test_linux_pageout_targets_private_mappings_and_measures_rss_change(monkeypatch):
    import builtins
    import io

    monkeypatch.setattr("core.process_manager.is_linux", lambda: True)
    monkeypatch.setattr(
        os,
        "uname",
        lambda: SimpleNamespace(machine="x86_64"),
        raising=False,
    )
    monkeypatch.setattr(os, "pidfd_open", lambda pid: 77, raising=False)
    monkeypatch.setattr(os, "sysconf", lambda key: 4096, raising=False)
    closed = []
    monkeypatch.setattr(os, "close", lambda pidfd: closed.append(pidfd))
    rss_values = iter([100 * 1024 * 1024, 88 * 1024 * 1024])
    monkeypatch.setattr(
        "core.process_manager.psutil.Process",
        lambda pid: SimpleNamespace(
            memory_info=lambda: SimpleNamespace(rss=next(rss_values))
        ),
    )
    maps = (
        "1000-5000 rw-p 00000000 00:00 0 [heap]\n"
        "6000-9000 rw-s 00000000 00:00 0 /shared\n"
    )
    monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: io.StringIO(maps))
    monkeypatch.setattr(
        "core.process_manager.ctypes.CDLL",
        lambda *args, **kwargs: SimpleNamespace(syscall=SimpleNamespace()),
    )
    advised = []
    monkeypatch.setattr(
        ProcessManager,
        "_advise_linux_pages",
        staticmethod(
            lambda syscall, number, pidfd, start, length: (
                advised.append((pidfd, start, length)) or length
            )
        ),
    )

    reclaimed, warning = ProcessManager._trim_working_set(50030)

    assert reclaimed == 12 * 1024 * 1024
    assert warning is None
    assert advised == [(77, 0x1000, 0x4000)]
    assert closed == [77]


def test_linux_process_madvise_uses_remote_iovec_and_pageout_advice():
    calls = []

    def fake_syscall(number, pidfd, iovec_pointer, count, advice, flags):
        vector = ctypes.cast(
            iovec_pointer,
            ctypes.POINTER(process_manager_module._LinuxIOVec),
        ).contents
        calls.append(
            (
                number,
                pidfd,
                vector.base,
                vector.length,
                count.value,
                advice,
                flags,
            )
        )
        return vector.length

    advised = ProcessManager._advise_linux_pages(
        fake_syscall,
        440,
        77,
        0x1000,
        4096,
    )

    assert advised == 4096
    assert calls == [(440, 77, 0x1000, 4096, 1, 21, 0)]


def test_linux_active_window_detection_uses_xdotool_on_x11(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr("core.system_monitor.shutil.which", lambda name: "/usr/bin/xdotool")
    outputs = iter(["0x42\n", "1234\n", "FocusOS test window\n"])
    monkeypatch.setattr(
        "core.system_monitor.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=next(outputs)),
    )
    monkeypatch.setattr(
        "core.system_monitor.psutil.Process",
        lambda pid: SimpleNamespace(name=lambda: "editor"),
    )

    result = SystemMonitor._get_linux_active_window()

    assert result == {
        "application": "editor",
        "title": "FocusOS test window",
        "pid": 1234,
        "warning": None,
    }


def test_linux_active_window_detection_does_not_guess_under_wayland(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
    monkeypatch.delenv("XDG_SESSION_DESKTOP", raising=False)
    monkeypatch.delenv("DESKTOP_SESSION", raising=False)
    run_calls = []
    monkeypatch.setattr(
        "core.system_monitor.subprocess.run",
        lambda *args, **kwargs: run_calls.append(args),
    )

    result = SystemMonitor._get_linux_active_window()

    assert result["pid"] is None
    assert "Wayland" in result["warning"]
    assert run_calls == []


def test_gnome_wayland_extension_installs_for_current_user_and_enables(monkeypatch, tmp_path):
    source = tmp_path / "extension-source"
    source.mkdir()
    (source / "metadata.json").write_text("metadata", encoding="utf-8")
    (source / "extension.js").write_text("extension", encoding="utf-8")
    home = tmp_path / "home"
    monkeypatch.setattr(gnome_focus, "_extension_source", lambda: source)
    monkeypatch.setattr(gnome_focus.shutil, "which", lambda command: "/usr/bin/gnome-extensions")
    monkeypatch.setattr(gnome_focus.Path, "home", lambda: home)
    calls = []
    monkeypatch.setattr(
        gnome_focus.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs))
        or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    warning = gnome_focus.ensure_extension_enabled()

    extension_dir = (
        home / ".local" / "share" / "gnome-shell" / "extensions" / gnome_focus.EXTENSION_UUID
    )
    assert warning is None
    assert (extension_dir / "extension.js").read_text(encoding="utf-8") == "extension"
    assert calls[0][0] == ["/usr/bin/gnome-extensions", "enable", gnome_focus.EXTENSION_UUID]


def test_gnome_wayland_active_window_reads_local_dbus_response(monkeypatch):
    monkeypatch.setattr(gnome_focus.shutil, "which", lambda command: "/usr/bin/gdbus")
    state = {
        "pid": 1234,
        "application": "org.example.Editor",
        "title": "FocusOS.py",
        "warning": None,
    }
    calls = []
    monkeypatch.setattr(
        gnome_focus.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command)
        or SimpleNamespace(
            stdout=f"({json.dumps(json.dumps(state))},)",
        ),
    )

    result = gnome_focus.get_active_window()

    assert result == state
    assert calls[0][-1] == gnome_focus.DBUS_METHOD


def test_wayland_focus_auto_installs_extension_for_gnome(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    monkeypatch.setattr("core.system_monitor.is_gnome_wayland", lambda: True)
    monkeypatch.setattr(SystemMonitor, "_gnome_setup_checked", False)
    monkeypatch.setattr(SystemMonitor, "_gnome_setup_warning", None)
    setup_calls = []
    monkeypatch.setattr(
        "core.system_monitor.ensure_extension_enabled",
        lambda: setup_calls.append(True),
    )
    state = {"pid": 900, "application": "editor", "title": "code.py", "warning": None}
    monkeypatch.setattr(
        "core.system_monitor.get_gnome_active_window",
        lambda: state,
    )

    result = SystemMonitor._get_linux_active_window()

    assert result == state
    assert setup_calls == [True]
    assert SystemMonitor._get_linux_active_window() == state
    assert setup_calls == [True]


def test_elevated_restart_requests_uac_and_waits_for_old_instance(monkeypatch):
    launch = {}
    monkeypatch.setattr(elevation, "supports_admin_restart", lambda: True)
    monkeypatch.setattr(elevation.sys, "executable", r"C:\Python\python.exe")
    monkeypatch.setattr(
        elevation,
        "_shell_execute_runas",
        lambda executable, parameters, cwd: (
            launch.update(
                executable=executable,
                parameters=parameters,
                cwd=cwd,
            )
            or 33
        ),
    )

    result = elevation.request_elevated_restart(
        [r"D:\FocusOS\main.py", "--terminal"],
        wait_for_pid=321,
    )

    assert result is None
    assert launch["executable"] == r"C:\Python\python.exe"
    assert "--wait-for-process 321" in launch["parameters"]
    assert r"D:\FocusOS\main.py" in launch["parameters"]
    assert "--terminal" in launch["parameters"]


def test_elevated_restart_reports_uac_cancellation(monkeypatch):
    monkeypatch.setattr(elevation, "supports_admin_restart", lambda: True)
    monkeypatch.setattr(
        elevation,
        "_shell_execute_runas",
        lambda executable, parameters, cwd: 5,
    )

    error = elevation.request_elevated_restart([r"D:\FocusOS\main.py"], 321)

    assert error is not None
    assert "cancelled" in error


def test_elevated_restart_waits_for_previous_process(monkeypatch):
    waited = []

    class PreviousProcess:
        def wait(self):
            waited.append(True)

    monkeypatch.setattr(elevation.psutil, "Process", lambda pid: PreviousProcess())

    elevation.wait_for_process_exit(321)

    assert waited == [True]


def test_auto_optimization_skips_memory_trim_if_foreground_changes():
    now = [0.0]
    username = psutil.Process().username()
    focused = ManagedFakeProcess(50013, "Editor.exe", username)
    background = ManagedFakeProcess(50014, "Browser.exe", username)
    processes = {50013: focused, 50014: background}
    active_pids = iter([50013, 50013, 50014])
    trim_calls = []
    manager = ProcessManager(
        suspend_after_seconds=120,
        clock=lambda: now[0],
        process_factory=lambda pid: processes[pid],
        active_pid_provider=lambda: next(active_pids),
        working_set_trimmer=lambda pid: (
            trim_calls.append(pid) or (8 * 1024 * 1024, None)
        ),
    )
    manager.auto_optimize_user_processes = True
    process_info = [
        {"pid": 50013, "name": "Editor.exe", "create_time": 123.0},
        {"pid": 50014, "name": "Browser.exe", "create_time": 123.0},
    ]

    manager.build_priority_plan(process_info, focus_pid=50013)
    now[0] = 120.0
    manager.build_priority_plan(process_info, focus_pid=50013)

    assert trim_calls == []
    assert manager.working_set_trimmed_bytes == 0
    manager.restore_all()


def test_process_manager_never_suspends_protected_system_processes():
    username = psutil.Process().username()
    process = ManagedFakeProcess(50002, "svchost.exe", username)
    manager = ProcessManager(
        allowlist=("svchost.exe",),
        suspend_after_seconds=0,
        process_factory=lambda pid: process,
    )
    process_info = {
        "pid": 50002,
        "name": "svchost.exe",
        "create_time": 123.0,
        "cpu_percent": 1.0,
    }

    plan = manager.build_priority_plan([process_info], focus_pid=None)

    assert plan[0]["suspended"] is False
    assert process._suspend_calls == 0
    assert process.nice() == 0


def test_process_manager_rechecks_foreground_before_suspending():
    now = [0.0]
    username = psutil.Process().username()
    process = ManagedFakeProcess(50003, "Editor.exe", username)
    manager = ProcessManager(
        allowlist=("Editor.exe",),
        suspend_after_seconds=300,
        clock=lambda: now[0],
        process_factory=lambda pid: process,
        active_pid_provider=lambda: 50003,
    )
    process_info = {
        "pid": 50003,
        "name": "Editor.exe",
        "create_time": 123.0,
        "cpu_percent": 1.0,
    }
    manager.build_priority_plan([process_info], focus_pid=None)

    now[0] = 300.0
    plan = manager.build_priority_plan([process_info], focus_pid=None)

    assert plan[0]["suspended"] is False
    assert process._suspend_calls == 0


def test_process_manager_rechecks_foreground_immediately_before_auto_suspend():
    username = psutil.Process().username()
    process = ManagedFakeProcess(50008, "Editor.exe", username)
    active_pids = iter([10, 50008])
    manager = ProcessManager(
        suspend_after_seconds=0,
        process_factory=lambda pid: process,
        active_pid_provider=lambda: next(active_pids),
        selected_instances={(50008, 123.0)},
    )
    process_info = {
        "pid": 50008,
        "name": "Editor.exe",
        "create_time": 123.0,
        "cpu_percent": 1.0,
    }

    plan = manager.build_priority_plan([process_info], focus_pid=10)

    assert plan[0]["suspended"] is False
    assert process._suspend_calls == 0


def test_windows_working_set_trim_measures_and_closes_process_handle(monkeypatch):
    import ctypes

    class FakeFunction:
        def __init__(self, callback):
            self.callback = callback

        def __call__(self, *args):
            return self.callback(*args)

    closed_handles = []
    kernel32 = SimpleNamespace(
        OpenProcess=FakeFunction(lambda *args: 123),
        CloseHandle=FakeFunction(lambda handle: closed_handles.append(handle) or 1),
    )
    psapi = SimpleNamespace(EmptyWorkingSet=FakeFunction(lambda handle: 1))
    monkeypatch.setattr("core.process_manager.os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        "core.process_manager.ctypes.WinDLL",
        lambda name, use_last_error: kernel32 if name == "kernel32" else psapi,
    )
    memory_values = iter([100 * 1024 * 1024, 40 * 1024 * 1024])

    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid

        def memory_info(self):
            return SimpleNamespace(rss=next(memory_values))

    monkeypatch.setattr("core.process_manager.psutil.Process", FakeProcess)

    trimmed, warning = ProcessManager._trim_working_set(50009)

    assert trimmed == 60 * 1024 * 1024
    assert warning is None
    assert closed_handles == [123]


def test_manual_ram_control_requires_user_selection_and_restores_process():
    username = psutil.Process().username()
    process = ManagedFakeProcess(50004, "Editor.exe", username)
    active_pid = [10]
    manager = ProcessManager(
        process_factory=lambda pid: process,
        active_pid_provider=lambda: active_pid[0],
        working_set_trimmer=lambda pid: (25 * 1024 * 1024, None),
    )
    candidate = {
        "pid": 50004,
        "name": "Editor.exe",
        "create_time": 123.0,
        "memory_rss": 300 * 1024 * 1024,
    }

    listed = manager.list_suspend_candidates([candidate], active_pid=10)
    trimmed_bytes, warning = manager.suspend_selected_process(50004, 123.0, "Editor.exe")

    assert listed[0]["memory_mb"] == 300.0
    assert trimmed_bytes == 25 * 1024 * 1024
    assert warning is None
    assert process._suspend_calls == 1
    assert manager.suspended_count == 1

    active_pid[0] = 50004
    assert manager.resume_selected_process(50004, 123.0) is None
    assert process._resume_calls == 1
    assert manager.suspended_count == 0


def test_manual_ram_control_refuses_foreground_or_unverified_process():
    username = psutil.Process().username()
    process = ManagedFakeProcess(50005, "Editor.exe", username)
    active_pid = [50005]
    manager = ProcessManager(
        process_factory=lambda pid: process,
        active_pid_provider=lambda: active_pid[0],
    )
    candidate = {
        "pid": 50005,
        "name": "Editor.exe",
        "create_time": 123.0,
        "memory_rss": 10,
    }

    assert manager.list_suspend_candidates([candidate], active_pid=50005) == []
    assert manager.list_suspend_candidates([candidate], active_pid=None) == []
    with pytest.raises(RuntimeError, match="currently in the foreground"):
        manager.suspend_selected_process(50005, 123.0, "Editor.exe")
    assert process._suspend_calls == 0


def test_storage_manager_lists_old_files_without_deleting_them(tmp_path):
    old_file = tmp_path / "old.tmp"
    recent_file = tmp_path / "recent.tmp"
    old_file.write_text("old")
    recent_file.write_text("recent")
    now = 2_000_000_000.0
    old_time = now - (8 * 24 * 60 * 60)
    os.utime(old_file, (old_time, old_time))
    os.utime(recent_file, (now, now))

    result = StorageManager(
        roots=[Path(tmp_path)],
        min_age_days=7,
        clock=lambda: now,
    ).scan_candidates()

    assert result["candidate_count"] == 1
    assert result["candidates"][0]["path"] == str(old_file)
    assert result["total_bytes"] == 3
    assert old_file.exists()
    assert recent_file.exists()


def test_storage_manager_one_hour_cutoff_excludes_newer_files(tmp_path):
    old_file = tmp_path / "older-than-one-hour.tmp"
    recent_file = tmp_path / "newer-than-one-hour.tmp"
    old_file.write_text("old")
    recent_file.write_text("recent")
    now = 2_000_000_000.0
    os.utime(old_file, (now - 3601, now - 3601))
    os.utime(recent_file, (now - 3599, now - 3599))

    result = StorageManager(
        roots=[tmp_path],
        min_age_seconds=CLEANUP_AUTO_MIN_AGE_SECONDS,
        clock=lambda: now,
    ).scan_candidates()

    assert result["candidate_count"] == 1
    assert result["candidates"][0]["path"] == str(old_file)
    assert recent_file.exists()


def test_storage_manager_skips_file_changed_since_preview(tmp_path):
    candidate = tmp_path / "reviewed.tmp"
    candidate.write_text("old")
    now = 2_000_000_000.0
    old_time = now - (8 * 24 * 60 * 60)
    os.utime(candidate, (old_time, old_time))
    manager = StorageManager(
        roots=[tmp_path],
        min_age_days=7,
        clock=lambda: now,
        file_deleter=lambda path: path.unlink(),
    )
    preview = manager.scan_candidates()["candidates"]
    candidate.write_text("changed after preview")
    os.utime(candidate, (old_time, old_time))

    result = manager.delete_approved_candidates(preview)

    assert result["removed_count"] == 0
    assert "changed" in result["errors"][0]
    assert candidate.exists()


def test_storage_manager_deletes_only_approved_old_direct_files(tmp_path):
    root = tmp_path / "Temp"
    root.mkdir()
    nested = root / "nested"
    nested.mkdir()
    old_file = root / "old.tmp"
    nested_file = nested / "nested.tmp"
    old_file.write_text("old")
    nested_file.write_text("nested")
    now = 2_000_000_000.0
    old_time = now - (8 * 24 * 60 * 60)
    os.utime(old_file, (old_time, old_time))
    os.utime(nested_file, (old_time, old_time))
    manager = StorageManager(roots=[root], min_age_days=7, clock=lambda: now)
    result = manager.scan_candidates()

    cleanup = manager.delete_approved_candidates(result["candidates"])

    assert cleanup["removed_count"] == 1
    assert cleanup["reclaimed_bytes"] == 3
    assert not old_file.exists()
    assert nested_file.exists()


def test_storage_manager_filters_dumps_and_logs_to_requested_extensions(tmp_path):
    dump = tmp_path / "old.dmp"
    diagnostic_log = tmp_path / "old.log"
    unrelated = tmp_path / "old.txt"
    for path in (dump, diagnostic_log, unrelated):
        path.write_text("old")
    now = 2_000_000_000.0
    old_time = now - (31 * 24 * 60 * 60)
    for path in (dump, diagnostic_log, unrelated):
        os.utime(path, (old_time, old_time))

    result = StorageManager(
        roots=[tmp_path],
        min_age_days=30,
        clock=lambda: now,
        direct_children_only=True,
        allowed_extensions={".dmp", ".log"},
    ).scan_candidates()

    assert result["candidate_count"] == 2
    assert {Path(item["path"]).suffix for item in result["candidates"]} == {".dmp", ".log"}


def test_storage_manager_reports_locked_files_without_deleting(tmp_path):
    locked_file = tmp_path / "old.log"
    locked_file.write_text("diagnostics")
    now = 2_000_000_000.0
    old_time = now - (31 * 24 * 60 * 60)
    os.utime(locked_file, (old_time, old_time))

    def reject_locked_file(path):
        raise PermissionError("file is in use")

    manager = StorageManager(
        roots=[tmp_path],
        min_age_days=30,
        clock=lambda: now,
        direct_children_only=True,
        allowed_extensions={".log"},
        file_deleter=reject_locked_file,
    )
    result = manager.scan_candidates()
    cleanup = manager.delete_approved_candidates(result["candidates"])

    assert cleanup["removed_count"] == 0
    assert "file is in use" in cleanup["errors"][0]
    assert locked_file.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows-only exclusive handle deletion")
def test_windows_safe_deleter_removes_only_the_temp_test_file(tmp_path):
    target = tmp_path / "focusos-delete-test.tmp"
    target.write_text("test fixture")

    StorageManager._delete_unlocked_file(target)

    assert not target.exists()


def test_storage_manager_direct_temp_scan_excludes_nested_files(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    top_level_file = tmp_path / "top.tmp"
    nested_file = nested / "nested.tmp"
    top_level_file.write_text("top")
    nested_file.write_text("nested")
    now = 2_000_000_000.0
    old_time = now - (8 * 24 * 60 * 60)
    os.utime(top_level_file, (old_time, old_time))
    os.utime(nested_file, (old_time, old_time))

    result = StorageManager(
        roots=[tmp_path],
        min_age_days=7,
        clock=lambda: now,
        direct_children_only=True,
    ).scan_candidates()

    assert result["candidate_count"] == 1
    assert result["candidates"][0]["path"] == str(top_level_file)


def test_storage_manager_refuses_cleanup_outside_selected_temp_root(tmp_path):
    root = tmp_path / "Temp"
    outside = tmp_path / "outside.tmp"
    root.mkdir()
    outside.write_text("not temp")
    manager = StorageManager(roots=[root], min_age_days=0)

    cleanup = manager.delete_approved_candidates([{"path": str(outside)}])

    assert cleanup["removed_count"] == 0
    assert outside.exists()


def test_cleanup_prompt_cancellation_keeps_temp_file(tmp_path, monkeypatch):
    old_file = tmp_path / "old.tmp"
    old_file.write_text("old")
    now = old_file.stat().st_mtime + (8 * 24 * 60 * 60)
    os.utime(old_file, (now - (8 * 24 * 60 * 60), now - (8 * 24 * 60 * 60)))
    monkeypatch.setattr("main.CLEANUP_MIN_AGE_DAYS", 7)
    monkeypatch.setattr("main.input", lambda prompt: "no", raising=False)

    review_and_clean_folder("TEMP", tmp_path, "DELETE TEMP")

    assert old_file.exists()


def test_cleanup_auto_deletes_eligible_file_without_confirmation(tmp_path, monkeypatch):
    old_file = tmp_path / "old.tmp"
    old_file.write_text("old")
    old_time = old_file.stat().st_mtime - (8 * 24 * 60 * 60)
    os.utime(old_file, (old_time, old_time))
    monkeypatch.setattr(
        StorageManager,
        "_delete_unlocked_file",
        staticmethod(lambda path: path.unlink()),
    )
    monkeypatch.setattr(
        "main.input",
        lambda prompt: (_ for _ in ()).throw(AssertionError("confirmation requested")),
        raising=False,
    )

    review_and_clean_folder(
        "TEMP",
        tmp_path,
        "DELETE TEMP",
        min_age_seconds=CLEANUP_AUTO_MIN_AGE_SECONDS,
        auto_delete=True,
    )

    assert not old_file.exists()


def test_focus_engine_initializes():
    engine = FocusEngine()
    assert engine.detect_active_application() is None
    assert engine.detect_current_task() == "idle"


def test_focus_engine_history_is_bounded():
    engine = FocusEngine()
    for index in range(400):
        engine.update_focus("VS Code", f"file-{index}.py")

    assert len(engine.task_history) == 300
    assert engine.task_history[-1]["active_window"] == "file-399.py"


def test_resource_manager_reports_pressure_without_applying_actions():
    manager = ResourceManager()

    normal = manager.assess(cpu_usage=25, ram_usage=60, disk_usage=70)
    critical = manager.assess(cpu_usage=96, ram_usage=90, disk_usage=99)

    assert normal == {"status": "NORMAL", "warnings": [], "automatic_actions": False}
    assert critical["status"] == "CRITICAL"
    assert len(critical["warnings"]) == 3
    assert critical["automatic_actions"] is False


def test_resource_manager_preserves_existing_overview_shape():
    assert ResourceManager().get_overview() == {
        "cpu_limit": 80.0,
        "ram_limit": 85.0,
        "status": "monitoring",
    }


def test_focus_engine_detects_coding_task():
    engine = FocusEngine()
    snapshot = engine.update_focus("VS Code", "focus_engine.py")

    assert snapshot["active_application"] == "VS Code"
    assert snapshot["focus_mode"] == "coding"
    assert 0 <= snapshot["focus_score"] <= 100


def test_focus_engine_detects_ml_training_task():
    engine = FocusEngine()
    snapshot = engine.update_focus("PyTorch", "Training model on dataset")

    assert snapshot["focus_mode"] == "ml_training"
    assert snapshot["focus_score"] >= 60


def test_python_training_is_classified_as_ml_training():
    engine = FocusEngine()
    assert engine.update_focus("python.exe", "model training")["focus_mode"] == "ml_training"


def test_runtime_updates_dashboard_state_and_recommends_without_applying():
    runtime = FocusRuntime(monitor=FakeMonitor())
    state = runtime.start()

    assert state["status"] == "RUNNING"
    assert state["focus_application"] == "Code.exe"
    assert state["focus_mode"] == "coding"
    assert state["cpu_usage"] == 31.5
    assert state["disk_usage"] == 0.0
    assert state["active_processes"] == 1
    assert state["background_processes"] == 1
    assert state["priority_plan"][0]["recommended_priority"] == "high"
    assert all(not process["applied"] for process in state["priority_plan"])
    assert state["top_memory_processes"][0]["name"] == "chrome.exe"
    assert state["top_memory_processes"][0]["memory_mb"] == 100.0


def test_runtime_control_states_preserve_read_only_process_handling():
    runtime = FocusRuntime(monitor=FakeMonitor())
    runtime.start()
    assert runtime.pause()["status"] == "PAUSED"
    assert runtime.resume()["status"] == "RUNNING"
    assert runtime.stop()["status"] == "STOPPED"

    with pytest.raises(RuntimeError):
        runtime.refresh()


def test_dashboard_and_local_api_share_runtime_state():
    monitor = FakeMonitor()
    runtime = FocusRuntime(monitor=monitor)
    api = FocusAPI(runtime)
    dashboard = MainWindow(runtime)
    api.create_app()

    state = dashboard.control("start")
    assert api.get_state() == state
    assert monitor.calls == 2
    assert dashboard.render()["state"] == state
    assert monitor.calls == 3


def test_local_api_exposes_runtime_state_and_controls():
    api = FocusAPI(FocusRuntime(monitor=FakeMonitor()))
    app = api.create_app()
    endpoints = {route.path: route.endpoint for route in app.routes if hasattr(route, "endpoint")}

    assert endpoints["/health"]() == {"status": "ready"}
    assert endpoints["/start"]()["status"] == "RUNNING"
    assert endpoints["/state"]()["focus_application"] == "Code.exe"
    assert endpoints["/pause"]()["status"] == "PAUSED"
    assert endpoints["/resume"]()["status"] == "RUNNING"
    assert endpoints["/stop"]()["status"] == "STOPPED"

    with pytest.raises(HTTPException) as error:
        endpoints["/pause"]()
    assert error.value.status_code == 409
