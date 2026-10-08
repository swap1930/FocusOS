"""Smart application lifecycle management."""


class AppManager:
    """Tracks installed apps and active workloads."""

    def __init__(self):
        self.installed_apps = []

    def register_app(self, app_name: str):
        """Add an app to the managed application list."""
        self.installed_apps.append(app_name)
        return self.installed_apps
