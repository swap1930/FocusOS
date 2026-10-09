"""Main dashboard window for display and controls."""

from typing import Dict, Optional

from core.focus_runtime import FocusRuntime


class MainWindow:
    """Provides the dashboard with the central FocusOS state and controls."""

    def __init__(self, runtime: Optional[FocusRuntime] = None):
        self.title = "FocusOS"
        self.runtime = runtime or FocusRuntime()

    def render(self) -> Dict[str, object]:
        """Return dashboard content from the shared runtime state."""
        state = (
            self.runtime.refresh()
            if self.runtime.state.status in {"RUNNING", "PAUSED"}
            else self.runtime.snapshot()
        )
        return {"title": self.title, "state": state}

    def control(self, action: str) -> Dict[str, object]:
        """Execute a supported dashboard control against the runtime."""
        actions = {
            "start": self.runtime.start,
            "pause": self.runtime.pause,
            "resume": self.runtime.resume,
            "stop": self.runtime.stop,
            "emergency_disable": self.runtime.emergency_disable,
        }
        if action not in actions:
            raise ValueError(f"Unsupported FocusOS control: {action}")
        return actions[action]()
