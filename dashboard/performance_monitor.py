"""Performance monitoring and chart aggregation for the dashboard."""


class PerformanceMonitor:
    """Collects live metrics for UI display."""

    def __init__(self):
        self.metrics = {}

    def update(self, metric_name: str, value: float):
        """Store a new metric value."""
        self.metrics[metric_name] = value
        return self.metrics
