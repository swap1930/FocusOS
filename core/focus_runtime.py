"""Central FocusOS runtime state and user controls."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

from core.focus_engine import FocusEngine
from core.process_manager import ProcessManager
from core.system_monitor import SystemMonitor


@dataclass
class FocusOSState:
    """Current dashboard-facing state shared by FocusOS components."""

    status: str = "STOPPED"
    focus_application: Optional[str] = None
    focus_window: Optional[str] = None
    focus_mode: str = "idle"
    focus_score: int = 0
    cpu_usage: float = 0.0
    ram_usage: float = 0.0
    gpu_usage: Optional[float] = None
    active_processes: int = 0
    background_processes: int = 0
    suspended_processes: int = 0
    priority_plan: Optional[List[Dict[str, object]]] = None


class FocusRuntime:
    """Coordinate monitoring, focus detection, and safe process recommendations."""

    def __init__(
        self,
        monitor: Optional[SystemMonitor] = None,
        focus_engine: Optional[FocusEngine] = None,
        process_manager: Optional[ProcessManager] = None,
    ):
        self.monitor = monitor or SystemMonitor()
        self.focus_engine = focus_engine or FocusEngine()
        self.process_manager = process_manager or ProcessManager()
        self.state = FocusOSState()

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
        priority_plan = self.process_manager.build_priority_plan(processes, window.get("pid"))

        self.state.focus_application = application
        self.state.focus_window = title
        self.state.focus_mode = str(focus["focus_mode"])
        self.state.focus_score = int(focus["focus_score"])
        self.state.cpu_usage = float(metrics["cpu_usage"])
        self.state.ram_usage = float(metrics["ram_usage"])
        self.state.gpu_usage = metrics["gpu_usage"]
        self.state.active_processes = sum(item["classification"] == "active" for item in priority_plan)
        self.state.background_processes = sum(
            item["classification"] in {"background", "idle"} for item in priority_plan
        )
        self.state.priority_plan = priority_plan
        return self.snapshot()

    def snapshot(self) -> Dict[str, object]:
        """Return the shared state in a JSON-serializable form."""
        return asdict(self.state)
