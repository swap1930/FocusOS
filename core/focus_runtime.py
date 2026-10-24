"""Central FocusOS runtime state and user controls."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from config.settings import (
    AUTO_OPTIMIZE_USER_PROCESSES,
    AUTO_SUSPEND_ALLOWLIST,
    AUTO_SUSPEND_DELAY_SECONDS,
    ML_POWER_MODE_MEMORY_TRIM_DELAY,
    RESOURCE_PROFILE_DEFAULT,
    RESOURCE_PROFILES,
    TASK_PROFILE_MAP,
)
from core.focus_engine import FocusEngine
from core.platform_support import is_linux, is_windows
from core.process_manager import ProcessManager
from core.resource_manager import ResourceManager
from core.storage_manager import StorageManager
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
    disk_cleaned_bytes: int = 0
    last_disk_cleanup_summary: Optional[str] = None
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
    auto_resource_profile: bool = True
    ml_power_mode_active: bool = False
    ml_power_mode_enabled: bool = False
    ml_training_target_pid: Optional[int] = None
    ml_training_target_name: Optional[str] = None


class FocusRuntime:
    """Coordinate monitoring, focus detection, and safe process recommendations."""

    def __init__(
        self,
        monitor: Optional[SystemMonitor] = None,
        focus_engine: Optional[FocusEngine] = None,
        process_manager: Optional[ProcessManager] = None,
        resource_manager: Optional[ResourceManager] = None,
        storage_manager: Optional[StorageManager] = None,
    ):
        self.monitor = monitor or SystemMonitor()
        self.focus_engine = focus_engine or FocusEngine()
        self.resource_manager = resource_manager or ResourceManager()
        self.storage_manager = storage_manager or StorageManager()
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
        self.auto_resource_profile = True
        self._manual_profile: Optional[str] = None
        # ML focus boosting is opt-in, while the displayed toggle may still
        # reflect automatic detection until the user explicitly changes it.
        self._ml_power_mode_enabled = False
        self._ml_target_pid: Optional[int] = None
        self._ml_target_name: Optional[str] = None
        self._ml_power_mode_was_active: bool = False
        self.platform = "Windows" if is_windows() else "Linux" if is_linux() else "Unsupported"
        self.state = FocusOSState()

    def clean_disk(
        self,
        empty_recycle_bin: bool = False,
        min_age_seconds: Optional[float] = None,
    ) -> Dict[str, object]:
        """Safely free disk space by removing eligible aged temp, cache, and prefetch files."""
        result = self.storage_manager.clean_all_safe_caches(min_age_seconds=min_age_seconds)
        reclaimed_bytes = int(result.get("reclaimed_bytes", 0))
        recycle_bytes = 0

        if empty_recycle_bin and is_windows():
            try:
                bin_info = StorageManager.recycle_bin_usage()
                if bin_info.get("items", 0) > 0:
                    recycle_bytes = int(bin_info.get("bytes", 0))
                    StorageManager.empty_recycle_bin()
                    reclaimed_bytes += recycle_bytes
            except OSError as err:
                result.setdefault("errors", []).append(f"Recycle Bin cleanup warning: {err}")

        self.state.disk_cleaned_bytes += reclaimed_bytes
        reclaimed_mb = round(reclaimed_bytes / (1024 * 1024), 2)
        removed_count = int(result.get("removed_count", 0))
        summary = (
            f"Freed {reclaimed_mb:.1f} MB ({removed_count} files cleaned)"
            if reclaimed_bytes > 0
            else "No eligible temporary files found to clean."
        )
        self.state.last_disk_cleanup_summary = summary

        if self.state.status in {"RUNNING", "PAUSED"}:
            self.refresh()
        else:
            try:
                metrics = self.monitor.collect()
                self.state.disk_free_bytes = int(metrics.get("disk_free_bytes", self.state.disk_free_bytes))
                self.state.disk_usage = float(metrics.get("disk_usage", self.state.disk_usage))
            except Exception:
                pass

        return {
            **result,
            "reclaimed_bytes": reclaimed_bytes,
            "reclaimed_mb": reclaimed_mb,
            "summary": summary,
        }

    def set_ml_power_mode(
        self,
        enabled: bool,
        target_pid: Optional[int] = None,
    ) -> Dict[str, object]:
        """Enable ML focus for a selected process and restore policy when disabled."""
        self._ml_power_mode_enabled = bool(enabled)
        self._ml_target_pid = target_pid if enabled else None
        self._ml_target_name = None
        self.state.ml_power_mode_enabled = self._ml_power_mode_enabled
        self.state.ml_training_target_pid = self._ml_target_pid
        if self.state.status in {"RUNNING", "PAUSED"}:
            return self.refresh()
        if not self._ml_power_mode_enabled:
            self.state.ml_training_target_pid = None
            self.state.ml_training_target_name = None
            self.process_manager.ml_power_mode = False
            if self._ml_power_mode_was_active:
                self.process_manager.restore_all()
                settings = RESOURCE_PROFILES.get(self.resource_profile, {})
                self.process_manager.suspend_after_seconds = float(
                    settings.get("suspend_delay_seconds", AUTO_SUSPEND_DELAY_SECONDS)
                )
                self._ml_power_mode_was_active = False
            self.state.ml_power_mode_active = False
        return self.snapshot()

    def get_recommended_profile(self, focus_mode: str) -> str:
        """Map the detected task/tab mode to an optimal resource profile."""
        return TASK_PROFILE_MAP.get(focus_mode, RESOURCE_PROFILE_DEFAULT)

    def apply_resource_profile(self, profile: str) -> None:
        """Apply warning thresholds and suspension delay for the given profile."""
        if profile not in RESOURCE_PROFILES:
            raise ValueError(f"Unknown resource profile: {profile}")
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

    def set_resource_profile(self, profile: str) -> Dict[str, object]:
        """Manually switch resource policy and lock profile selection."""
        if profile not in RESOURCE_PROFILES:
            raise ValueError(f"Unknown resource profile: {profile}")

        self._manual_profile = profile
        self.state.auto_resource_profile = False
        restore_errors = self.process_manager.restore_all()
        self.apply_resource_profile(profile)
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

    def enable_auto_resource_profile(self) -> Dict[str, object]:
        """Switch back to automatic profile tuning based on foreground tab/window."""
        self._manual_profile = None
        self.auto_resource_profile = True
        self.state.auto_resource_profile = True
        if self.state.status in {"RUNNING", "PAUSED"}:
            return self.refresh()
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
        focus_mode = str(focus["focus_mode"])

        if self.auto_resource_profile and self._manual_profile is None:
            recommended = self.get_recommended_profile(focus_mode)
            if recommended in RESOURCE_PROFILES and recommended != self.resource_profile:
                self.apply_resource_profile(recommended)

        # ------------------------------------------------------------------
        # ML mode is explicitly user-selected and targets one process. Normal
        # focus mode continues to follow the current foreground application.
        foreground_pid = window.get("pid")
        process_by_pid = {
            item.get("pid"): item
            for item in metrics.get("processes", [])
            if isinstance(item, dict)
        }
        target_process = process_by_pid.get(self._ml_target_pid)
        if target_process is not None:
            self._ml_target_name = str(target_process.get("name", "Unknown process"))
        elif self._ml_target_pid is not None:
            self._ml_target_pid = None
            self._ml_target_name = None
            self.state.ml_training_target_pid = None
            self.state.ml_training_target_name = None
        ml_power_mode_active = (
            self._ml_power_mode_enabled
            and self.state.status == "RUNNING"
            and self._ml_target_pid is not None
        )
        self.state.ml_power_mode_enabled = self._ml_power_mode_enabled
        self.state.ml_training_target_pid = self._ml_target_pid
        self.state.ml_training_target_name = self._ml_target_name

        if ml_power_mode_active and not self._ml_power_mode_was_active:
            # ML mode rapidly trims eligible background working sets without
            # suspending arbitrary applications or changing their lifecycle.
            self.process_manager._ml_memory_trim_after_seconds = ML_POWER_MODE_MEMORY_TRIM_DELAY
            # Clear delay tracking so background apps are trimmed next cycle
            self.process_manager._background_since.clear()
            self.process_manager._trimmed_instances.clear()
        elif not ml_power_mode_active and self._ml_power_mode_was_active:
            # Exiting ML Power Mode: restore the current profile delay
            profile_settings = RESOURCE_PROFILES.get(self.resource_profile, {})
            self.process_manager.suspend_after_seconds = float(
                profile_settings.get("suspend_delay_seconds", AUTO_SUSPEND_DELAY_SECONDS)
            )
            self.process_manager._ml_memory_trim_after_seconds = None
            # Restore all background process priorities to normal
            self.process_manager.restore_all()

        self._ml_power_mode_was_active = ml_power_mode_active
        self.state.ml_power_mode_active = ml_power_mode_active

        # Propagate the power mode flag to ProcessManager so boost class is correct.
        self.process_manager.ml_power_mode = ml_power_mode_active

        processes = metrics["processes"]
        if not isinstance(processes, list):
            raise TypeError("System monitor processes must be a list.")
        priority_focus_pid = (
            self._ml_target_pid if ml_power_mode_active else foreground_pid
        )
        priority_plan = self.process_manager.build_priority_plan(
            processes,
            priority_focus_pid,
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
