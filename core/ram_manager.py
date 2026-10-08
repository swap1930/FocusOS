"""RAM management policy for idle and suspended applications."""


class RAMManager:
    """Safely frees memory from low-priority tasks."""

    def __init__(self):
        self.suspended_apps = []

    def suspend_idle_app(self, app_name: str):
        """Move an idle app into a safe suspended state."""
        self.suspended_apps.append(app_name)
        return self.suspended_apps
