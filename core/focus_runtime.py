"""Central FocusOS runtime state and user controls."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from config.settings import (
    AUTO_OPTIMIZE_USER_PROCESSES,
    AUTO_SUSPEND_ALLOWLIST,
    AUTO_SUSPEND_DELAY_SECONDS,
    RESOURCE_PROFILE_DEFAULT,
    RESOURCE_PROFILES,
)
from core.focus_engine import FocusEngine
from core.platform_support import is_linux, is_windows
from core.process_manager import ProcessManager
from core.resource_manager import ResourceManager
from core.system_monitor import SystemMonitor


@dataclass
class FocusOSState:
    """Current dashboard-facing state shared by FocusOS components."""

    status: str = "STOPPED"
    focus_application: Optional[str] = None
    focus_window: Optional[str] = None
    focus_detection_warning: Optional[str] = None
    focus_mode: str = "idle"
    focus_score: int = 0
    cpu_usage: float = 0.0
    ram_usage: float = 0.0
    ram_available_bytes: int = 0
    ram_total_bytes: int = 0
    disk_usage: float = 0.0
    disk_free_bytes: int = 0
    disk_total_bytes: int = 0
    gpu_usage: Optional[float] = None
    resource_status: str = "NORMAL"
    resource_warnings: List[str] = field(default_factory=list)
    active_processes: int = 0
    background_processes: int = 0
    suspended_processes: int = 0
    working_set_trimmed_bytes: int = 0
    priority_plan: Optional[List[Dict[str, object]]] = None
    top_memory_processes: List[Dict[str, object]] = field(default_factory=list)
    process_action_errors: List[str] = field(default_factory=list)
    resource_profile: str = RESOURCE_PROFILE_DEFAULT


class FocusRuntime:
    """Coordinate monitoring, focus detection, and safe process recommendations."""

    def __init__(
        self,
        monitor: Optional[SystemMonitor] = None,
        focus_engine: Optional[FocusEngine] = None,
        process_manager: Optional[ProcessManager] = None,
        resource_manager: Optional[ResourceManager] = None,
    ):
        self.monitor = monitor or SystemMonitor()
        self.focus_engine = focus_engine or FocusEngine()
        self.resource_manager = resource_manager or ResourceManager()
        active_pid_provider = getattr(self.monitor, "get_active_window_pid", None)
        if not callable(active_pid_provider):
            active_pid_provider = None
        self.process_manager = process_manager or ProcessManager(
            allowlist=AUTO_SUSPEND_ALLOWLIST,
            suspend_after_seconds=AUTO_SUSPEND_DELAY_SECONDS,
            active_pid_provider=active_pid_provider,
        )
        self.process_manager.auto_optimize_user_processes = (
            AUTO_OPTIMIZE_USER_PROCESSES and (is_windows() or is_linux())
        )
        self.resource_profile = RESOURCE_PROFILE_DEFAULT
        self.platform = "Windows" if is_windows() else "Linux" if is_linux() else "Unsupported"
        self.state = FocusOSState()

    def set_resource_profile(self, profile: str) -> Dict[str, object]:
        """Switch resource policy after restoring settings from the previous profile."""
        if profile not in RESOURCE_PROFILES:
            raise ValueError(f"Unknown resource profile: {profile}")

        restore_errors = self.process_manager.restore_all()
        settings = RESOURCE_PROFILES[profile]
        self.resource_profile = profile
        self.process_manager.suspend_after_seconds = float(
            settings["suspend_delay_seconds"]
        )
        self.resource_manager.set_warning_thresholds(
            float(settings["cpu_warning"]),
            float(settings["ram_warning"]),
            float(settings["disk_warning"]),
        )
        self.state.resource_profile = profile
        self.state.process_action_errors = restore_errors

        if self.state.status in {"RUNNING", "PAUSED"}:
            self.refresh()
            self.state.process_action_errors = [
                *restore_errors,
                *self.state.process_action_errors,
            ]
        else:
            self.state.suspended_processes = self.process_manager.suspended_count

        return self.snapshot()

    def start(self) -> Dict[str, object]:
        """Start monitoring and return the first state snapshot."""
        self.state.status = "RUNNING"
        return self.refresh()

    def pause(self) -> Dict[str, object]:
        """Disable optimization while leaving monitoring available."""
        if self.state.status != "RUNNING":
            raise RuntimeError("FocusOS can only be paused while it is running.")
        self.state.status = "PAUSED"
        return self.refresh()

    def resume(self) -> Dict[str, object]:
        """Resume monitoring and focus recommendations."""
        if self.state.status != "PAUSED":
            raise RuntimeError("FocusOS can only be resumed while it is paused.")
        self.state.status = "RUNNING"
        return self.refresh()

    def stop(self) -> Dict[str, object]:
        """Stop FocusOS monitoring without changing user processes."""
        self.state.process_action_errors = self.process_manager.restore_all()
        self.state.suspended_processes = self.process_manager.suspended_count
        self.state.status = "STOPPED"
        return self.snapshot()

    def emergency_disable(self) -> Dict[str, object]:
        """Immediately disable FocusOS actions without affecting other processes."""
        return self.stop()

    def refresh(self) -> Dict[str, object]:
        """Refresh metrics and focus state while monitoring is enabled."""
        if self.state.status not in {"RUNNING", "PAUSED"}:
            raise RuntimeError("FocusOS must be running or paused to refresh monitoring.")

        metrics = self.monitor.collect()
        window = metrics["active_window"]
        if not isinstance(window, dict):
            raise TypeError("System monitor active_window must be a mapping.")

        application = window.get("application")
        title = window.get("title")
        if application is not None and not isinstance(application, str):
            raise TypeError("Active application name must be a string or None.")
        if title is not None and not isinstance(title, str):
            raise TypeError("Active window title must be a string or None.")

        focus = self.focus_engine.update_focus(application, title)
        processes = metrics["processes"]
        if not isinstance(processes, list):
            raise TypeError("System monitor processes must be a list.")
        priority_plan = self.process_manager.build_priority_plan(
            processes,
            window.get("pid"),
            apply_controls=self.state.status == "RUNNING",
        )

        self.state.focus_application = application
        self.state.focus_window = title
        self.state.focus_detection_warning = (
            str(window["warning"]) if window.get("warning") else None
        )
        self.state.focus_mode = str(focus["focus_mode"])
        self.state.focus_score = int(focus["focus_score"])
        self.state.cpu_usage = float(metrics["cpu_usage"])
        self.state.ram_usage = float(metrics["ram_usage"])
        self.state.ram_available_bytes = int(metrics.get("ram_available_bytes", 0))
        self.state.ram_total_bytes = int(metrics.get("ram_total_bytes", 0))
        self.state.disk_usage = float(metrics.get("disk_usage", 0.0))
        self.state.disk_free_bytes = int(metrics.get("disk_free_bytes", 0))
        self.state.disk_total_bytes = int(metrics.get("disk_total_bytes", 0))
        self.state.gpu_usage = metrics["gpu_usage"]
        resource_assessment = self.resource_manager.assess(
            self.state.cpu_usage,
            self.state.ram_usage,
            self.state.disk_usage,
        )
        self.state.resource_status = str(resource_assessment["status"])
        self.state.resource_warnings = list(resource_assessment["warnings"])
        self.state.active_processes = sum(item["classification"] == "active" for item in priority_plan)
        self.state.background_processes = sum(
            item["classification"] in {"background", "idle"} for item in priority_plan
        )
        self.state.suspended_processes = sum(bool(item["suspended"]) for item in priority_plan)
        self.state.working_set_trimmed_bytes = self.process_manager.working_set_trimmed_bytes
        self.state.priority_plan = priority_plan
        self.state.top_memory_processes = sorted(
            (
                {
                    "pid": item["pid"],
                    "name": item["name"],
                    "memory_mb": round(float(item.get("memory_rss", 0)) / (1024 * 1024), 1),
                    "classification": item["classification"],
                }
                for item in priority_plan
            ),
            key=lambda item: float(item["memory_mb"]),
            reverse=True,
        )[:5]
        self.state.process_action_errors = list(self.process_manager.action_errors)
        return self.snapshot()

    def snapshot(self) -> Dict[str, object]:
        """Return the shared state in a JSON-serializable form."""
        return asdict(self.state)
