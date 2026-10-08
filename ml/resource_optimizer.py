"""Resource tuning logic for model training workloads."""


class ResourceOptimizer:
    """Sets resource priority during ML workloads."""

    def optimize(self, cpu: float, ram: float):
        """Return a tuned resource profile."""
        return {"cpu": cpu, "ram": ram, "priority": "high"}
