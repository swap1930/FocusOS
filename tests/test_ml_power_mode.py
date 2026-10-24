"""Tests for ML Power Mode – automatic resource maximisation for AI/ML training."""

import pytest

from config.settings import AUTO_SUSPEND_DELAY_SECONDS, ML_POWER_MODE_MEMORY_TRIM_DELAY
from core.focus_runtime import FocusRuntime


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class _SimpleProcessManager:
    """Minimal ProcessManager stand-in that tracks the fields FocusRuntime mutates."""

    auto_optimize_user_processes = False
    working_set_trimmed_bytes = 0
    action_errors: list = []

    def __init__(self, suspend_after_seconds: float = AUTO_SUSPEND_DELAY_SECONDS):
        self.suspend_after_seconds = suspend_after_seconds
        self.ml_power_mode = False
        self.suspended_count = 0
        self._background_since: dict = {}
        self._trimmed_instances: set = set()
        self._restore_all_called = 0
        self._clear_delay_called = 0

    def build_priority_plan(self, processes, focus_pid, apply_controls=True):
        return []

    def restore_all(self):
        self._restore_all_called += 1
        return []


class _TabMonitor:
    """Fake monitor that lets the test control the active window between calls."""

    def __init__(self, application: str, title: str, pid: int = 42, processes=None):
        self.active_window = {"application": application, "title": title, "pid": pid}
        self.processes = processes

    def collect(self):
        return {
            "cpu_usage": 55.0,
            "ram_usage": 40.0,
            "gpu_usage": None,
            "active_window": self.active_window,
            "processes": self.processes or [
                {
                    "pid": self.active_window["pid"],
                    "name": self.active_window["application"],
                    "cpu_percent": 80.0,
                    "memory_rss": 200 * 1024 * 1024,
                }
            ],
        }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_ml_mode_does_not_auto_enable_from_ml_window_title():
    """ML mode is a user choice, not an automatic title-based mode."""
    monitor = _TabMonitor("chrome.exe", "train_model.ipynb - Google Colab", pid=10)
    pm = _SimpleProcessManager()
    runtime = FocusRuntime(monitor=monitor, process_manager=pm)

    state = runtime.start()

    assert state["focus_mode"] == "ml_training", "focus_mode should be ml_training"
    assert state["ml_power_mode_active"] is False
    assert pm.ml_power_mode is False
    assert pm.suspend_after_seconds == 60
    assert getattr(pm, "_ml_memory_trim_after_seconds", None) is None


def test_ml_power_mode_not_active_for_normal_task():
    """ML Power Mode must NOT activate for a normal coding or browsing task."""
    monitor = _TabMonitor("Code.exe", "main.py - VS Code", pid=20)
    pm = _SimpleProcessManager()
    runtime = FocusRuntime(monitor=monitor, process_manager=pm)

    state = runtime.start()

    assert state["ml_power_mode_active"] is False
    assert pm.ml_power_mode is False
    # Normal mode keeps the standard suspension delay and has no ML trim timer.
    assert pm.suspend_after_seconds == 60
    assert getattr(pm, "_ml_memory_trim_after_seconds", None) is None


def test_ml_power_mode_restores_delay_when_selected_target_loses_focus():
    """Leaving the selected target disables ML boost and restores the delay."""
    monitor = _TabMonitor("chrome.exe", "train_model.ipynb - Google Colab", pid=30)
    pm = _SimpleProcessManager()
    runtime = FocusRuntime(monitor=monitor, process_manager=pm)

    runtime.set_ml_power_mode(True, target_pid=30)
    runtime.start()
    assert pm.suspend_after_seconds == 60
    assert pm._ml_memory_trim_after_seconds == ML_POWER_MODE_MEMORY_TRIM_DELAY

    # Switch focus away from the selected training process.
    monitor.active_window = {"application": "Code.exe", "title": "app.py - VS Code", "pid": 31}
    state = runtime.refresh()

    assert state["ml_power_mode_active"] is False
    assert pm.ml_power_mode is False
    # Delay must be restored to the profile's configured value (not the aggressive ML value)
    assert pm.suspend_after_seconds == 60
    assert pm._ml_memory_trim_after_seconds is None
    # restore_all() must have been called to reset process priorities
    assert pm._restore_all_called >= 1


def test_ml_power_mode_clears_background_since_on_entry():
    """On entering selected ML mode, background tracking state is cleared."""
    monitor = _TabMonitor("chrome.exe", "train_model.ipynb - Google Colab", pid=50)
    pm = _SimpleProcessManager()
    # Pre-populate some stale background tracking state
    pm._background_since["some_process"] = 1000.0
    pm._trimmed_instances.add("another_process")

    runtime = FocusRuntime(monitor=monitor, process_manager=pm)
    runtime.set_ml_power_mode(True, target_pid=50)
    runtime.start()

    assert pm._background_since == {}, "_background_since must be cleared on ML mode entry"
    assert pm._trimmed_instances == set(), "_trimmed_instances must be cleared on ML mode entry"


def test_ml_power_mode_stays_active_for_selected_training_process():
    """ML Power Mode persists while the selected training process is focused."""
    monitor = _TabMonitor("chrome.exe", "Kaggle Notebook - GPU Training", pid=60)
    pm = _SimpleProcessManager()
    runtime = FocusRuntime(monitor=monitor, process_manager=pm)

    runtime.set_ml_power_mode(True, target_pid=60)
    runtime.start()
    assert runtime.state.ml_power_mode_active is True

    # Three more refreshes – same ML tab, mode must persist
    for _ in range(3):
        state = runtime.refresh()
        assert state["ml_power_mode_active"] is True
        assert pm.ml_power_mode is True


def test_ml_task_classification_does_not_automatically_enable_power_mode():
    """A PyTorch title is classified but must not enable ML mode by itself."""
    monitor = _TabMonitor("python.exe", "Model Training - PyTorch", pid=70)
    pm = _SimpleProcessManager()
    runtime = FocusRuntime(monitor=monitor, process_manager=pm)

    state = runtime.start()

    assert state["focus_mode"] == "ml_training"
    assert state["ml_power_mode_active"] is False


def test_ml_power_mode_can_be_manually_disabled_and_restores_policy():
    monitor = _TabMonitor("chrome.exe", "Colab model training", pid=80)
    pm = _SimpleProcessManager()
    runtime = FocusRuntime(monitor=monitor, process_manager=pm)

    runtime.set_ml_power_mode(True, target_pid=80)
    runtime.start()
    assert pm.ml_power_mode is True

    state = runtime.set_ml_power_mode(False)

    assert state["ml_power_mode_enabled"] is False
    assert state["ml_power_mode_active"] is False
    assert pm.ml_power_mode is False
    assert pm.suspend_after_seconds == 60
    assert pm._ml_memory_trim_after_seconds is None
    assert pm._restore_all_called >= 1


def test_ml_power_mode_can_be_enabled_for_user_selected_process():
    monitor = _TabMonitor(
        "FocusOS.exe",
        "FocusOS Dashboard",
        pid=90,
        processes=[
            {"pid": 90, "name": "FocusOS.exe", "cpu_percent": 1.0, "memory_rss": 10},
            {"pid": 91, "name": "python.exe", "cpu_percent": 70.0, "memory_rss": 200},
        ],
    )
    pm = _SimpleProcessManager()
    runtime = FocusRuntime(monitor=monitor, process_manager=pm)

    runtime.set_ml_power_mode(True, target_pid=91)
    state = runtime.start()

    assert state["ml_power_mode_enabled"] is True
    assert state["ml_power_mode_active"] is True
    assert state["ml_training_target_pid"] == 91
    assert pm.ml_power_mode is True

    state = runtime.refresh()
    assert state["ml_power_mode_active"] is True
    assert state["ml_training_target_pid"] == 91

    state = runtime.set_ml_power_mode(False)
    assert state["ml_power_mode_active"] is False
    assert state["ml_training_target_pid"] is None
    assert pm.ml_power_mode is False
