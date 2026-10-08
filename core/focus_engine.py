"""Focus engine responsible for active-task detection."""


class FocusEngine:
    """Identifies the active application and workload context."""

    def __init__(self):
        self.active_app = None

    def detect_active_application(self):
        """Return the currently active application name."""
        return self.active_app

    def update_focus(self, app_name: str):
        """Update the current active application."""
        self.active_app = app_name
        return self.active_app
