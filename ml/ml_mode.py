"""High-priority ML training mode for FocusOS."""


class MLMode:
    """Boosts system focus when training workloads are detected."""

    def __init__(self):
        self.active = False

    def enable(self):
        """Activate ML training mode."""
        self.active = True
        return self.active
