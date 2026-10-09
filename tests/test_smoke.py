"""Smoke tests for the FocusOS focus engine."""

import pytest
import psutil
from fastapi import HTTPException

from api.focus_api import FocusAPI
from core.focus_engine import FocusEngine
from core.focus_runtime import FocusRuntime
from core.system_monitor import SystemMonitor
from dashboard.main_window import MainWindow


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
                {"pid": 12, "name": "Code.exe", "cpu_percent": 10.0},
                {"pid": 20, "name": "chrome.exe", "cpu_percent": 2.0},
            ],
        }


def test_system_monitor_skips_processes_that_exit_during_collection(monkeypatch):
    class FakeProcess:
        def __init__(self, pid, name, cpu_percent):
            self.info = {"pid": pid, "name": name}
            self._cpu_percent = cpu_percent

        def cpu_percent(self, interval=None):
            if isinstance(self._cpu_percent, Exception):
                raise self._cpu_percent
            return self._cpu_percent

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
    monkeypatch.setattr(psutil, "virtual_memory", lambda: type("Memory", (), {"percent": 50.0})())

    metrics = SystemMonitor().collect()

    assert metrics["processes"] == [{"pid": 1, "name": "Code.exe", "cpu_percent": 12.5}]


def test_focus_engine_initializes():
    engine = FocusEngine()
    assert engine.detect_active_application() is None
    assert engine.detect_current_task() == "idle"


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
    assert state["active_processes"] == 1
    assert state["background_processes"] == 1
    assert state["priority_plan"][0]["recommended_priority"] == "high"
    assert all(not process["applied"] for process in state["priority_plan"])


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
