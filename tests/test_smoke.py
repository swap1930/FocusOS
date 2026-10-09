"""Smoke tests for the FocusOS focus engine."""

import os
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest
from fastapi import HTTPException
import main as focusos_main

from api.focus_api import FocusAPI
from config.settings import AUTO_SUSPEND_DELAY_SECONDS, CLEANUP_AUTO_MIN_AGE_SECONDS
from core.focus_engine import FocusEngine
from core.focus_runtime import FocusRuntime
from core.process_manager import ProcessManager
from core.resource_manager import ResourceManager
from core.storage_manager import StorageManager
from core.system_monitor import SystemMonitor
from dashboard.main_window import MainWindow
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


def test_process_manager_suspends_and_restores_allowlisted_process_after_delay():
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


def test_selected_background_process_is_auto_suspended_after_two_minutes_and_restored():
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
            {"allowlist": set(), "selected_process_count": 0},
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
        ["main.py"] + (["--skip-disk-review"] if skip_disk_review else []),
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
