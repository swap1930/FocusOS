"""SQLite wrapper for persistence and state tracking."""


class DatabaseManager:
    """Manages evaluation, system state, and user history data."""

    def __init__(self, path: str = "focusos.db"):
        self.path = path

    def connect(self):
        """Return the configured database path."""
        return self.path
