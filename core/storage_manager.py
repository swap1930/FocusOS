"""Smart storage cleanup and safe file recommendations."""


class StorageManager:
    """Finds temporary or redundant files that may be safe to clean."""

    def __init__(self):
        self.safe_cleanup_targets = []

    def add_candidate(self, path: str):
        """Add a candidate to the cleanup queue."""
        self.safe_cleanup_targets.append(path)
        return self.safe_cleanup_targets
