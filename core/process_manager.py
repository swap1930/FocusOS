"""Background process classification and lifecycle controls."""


class ProcessManager:
    """Classifies processes as active, background, or safe to defer."""

    def __init__(self):
        self.processes = []

    def classify(self, process_name: str, cpu_usage: float = 0.0):
        """Return a priority categorization for a process."""
        if cpu_usage > 50:
            return "active"
        if process_name.lower().startswith("chrome"):
            return "background"
        return "idle"
