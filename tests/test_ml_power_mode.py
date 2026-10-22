"""Tests for ML Power Mode – automatic resource maximisation for AI/ML training."""

import pytest

from config.settings import AUTO_SUSPEND_DELAY_SECONDS, ML_POWER_MODE_SUSPEND_DELAY
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

    def __init__(self, application: str, title: str, pid: int = 42):
        self.active_window = {"application": application, "title": title, "pid": pid}

    def collect(self):
        return {
            "cpu_usage": 55.0,
            "ram_usage": 40.0,
            "gpu_usage": None,
            "active_window": self.active_window,
            "processes": [
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

def test_ml_power_mode_activates_on_ml_training_tab():
    """FocusRuntime must detect a Colab/ML tab and flag ml_power_mode_active."""
    monitor = _TabMonitor("chrome.exe", "train_model.ipynb - Google Colab", pid=10)
    pm = _SimpleProcessManager()
    runtime = FocusRuntime(monitor=monitor, process_manager=pm)

    state = runtime.start()

    assert state["focus_mode"] == "ml_training", "focus_mode should be ml_training"
    assert state["ml_power_mode_active"] is True, "ml_power_mode_active must be True"
    assert pm.ml_power_mode is True, "ProcessManager.ml_power_mode must be True"
    assert pm.suspend_after_seconds == ML_POWER_MODE_SUSPEND_DELAY, (
        f"suspend delay should be {ML_POWER_MODE_SUSPEND_DELAY}s in ML Power Mode, "
        f"got {pm.suspend_after_seconds}"
    )


def test_ml_power_mode_not_active_for_normal_task():
    """ML Power Mode must NOT activate for a normal coding or browsing task."""
    monitor = _TabMonitor("Code.exe", "main.py - VS Code", pid=20)
    pm = _SimpleProcessManager()
    runtime = FocusRuntime(monitor=monitor, process_manager=pm)

    state = runtime.start()

    assert state["ml_power_mode_active"] is False
    assert pm.ml_power_mode is False
    # Suspend delay should NOT be the aggressive ML value
    assert pm.suspend_after_seconds != ML_POWER_MODE_SUSPEND_DELAY


def test_ml_power_mode_restores_delay_on_exit():
    """When switching away from ML training, the suspend delay must be restored."""
    monitor = _TabMonitor("chrome.exe", "train_model.ipynb - Google Colab", pid=30)
    pm = _SimpleProcessManager()
    runtime = FocusRuntime(monitor=monitor, process_manager=pm)

    # Step 1: enter ML Power Mode
    runtime.start()
    assert pm.suspend_after_seconds == ML_POWER_MODE_SUSPEND_DELAY

    # Step 2: switch to a normal coding tab
    monitor.active_window = {"application": "Code.exe", "title": "app.py - VS Code", "pid": 31}
    state = runtime.refresh()

    assert state["ml_power_mode_active"] is False
    assert pm.ml_power_mode is False
    # Delay must be restored to the profile's configured value (not the aggressive ML value)
    assert pm.suspend_after_seconds != ML_POWER_MODE_SUSPEND_DELAY
    # restore_all() must have been called to reset process priorities
    assert pm._restore_all_called >= 1


def test_ml_power_mode_clears_background_since_on_entry():
    """On entering ML Power Mode the background-since timestamps must be wiped."""
    monitor = _TabMonitor("chrome.exe", "train_model.ipynb - Google Colab", pid=50)
    pm = _SimpleProcessManager()
    # Pre-populate some stale background tracking state
    pm._background_since["some_process"] = 1000.0
    pm._trimmed_instances.add("another_process")

    runtime = FocusRuntime(monitor=monitor, process_manager=pm)
    runtime.start()

    assert pm._background_since == {}, "_background_since must be cleared on ML mode entry"
    assert pm._trimmed_instances == set(), "_trimmed_instances must be cleared on ML mode entry"


def test_ml_power_mode_stays_active_across_refreshes():
    """ML Power Mode must remain active as long as focus_mode stays ml_training."""
    monitor = _TabMonitor("chrome.exe", "Kaggle Notebook - GPU Training", pid=60)
    pm = _SimpleProcessManager()
    runtime = FocusRuntime(monitor=monitor, process_manager=pm)

    runtime.start()
    assert runtime.state.ml_power_mode_active is True

    # Three more refreshes – same ML tab, mode must persist
    for _ in range(3):
        state = runtime.refresh()
        assert state["ml_power_mode_active"] is True
        assert pm.ml_power_mode is True


def test_ml_power_mode_pytorch_app():
    """Local PyTorch process should also trigger ML Power Mode."""
    monitor = _TabMonitor("python.exe", "Model Training - PyTorch", pid=70)
    pm = _SimpleProcessManager()
    runtime = FocusRuntime(monitor=monitor, process_manager=pm)

    state = runtime.start()

    assert state["focus_mode"] == "ml_training"
    assert state["ml_power_mode_active"] is True
