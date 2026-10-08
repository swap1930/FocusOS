"""Resource management entries for CPU, RAM, and process safety."""


class ResourceManager:
    """Coordinates monitoring and priority controls."""

    def __init__(self):
        self.cpu_limit = 80
        self.ram_limit = 75

    def get_overview(self):
        """Return a summary of resource usage."""
        return {
            "cpu_limit": self.cpu_limit,
            "ram_limit": self.ram_limit,
            "status": "monitoring",
        }
