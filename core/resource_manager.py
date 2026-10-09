"""Resource management entries for CPU, RAM, and process safety."""

from typing import Dict, List

class ResourceManager:
    """Assess resource pressure and summarize safe next steps."""

    def __init__(
        self,
        cpu_warning: float = 80.0,
        ram_warning: float = 85.0,
        disk_warning: float = 90.0,
        critical_threshold: float = 95.0,
    ):
        self.cpu_limit = cpu_warning
        self.ram_limit = ram_warning
        self.cpu_warning = cpu_warning
        self.ram_warning = ram_warning
        self.disk_warning = disk_warning
        self.critical_threshold = critical_threshold

    def assess(self, cpu_usage: float, ram_usage: float, disk_usage: float) -> Dict[str, object]:
        """Report pressure without taking destructive or unapproved actions."""
        metrics = {
            "cpu": (cpu_usage, self.cpu_warning),
            "ram": (ram_usage, self.ram_warning),
            "disk": (disk_usage, self.disk_warning),
        }
        warnings: List[str] = []
        critical = False
        for name, (value, warning_threshold) in metrics.items():
            if value >= self.critical_threshold:
                critical = True
                warnings.append(f"{name.upper()} usage is critically high ({value:.1f}%).")
            elif value >= warning_threshold:
                warnings.append(f"{name.upper()} usage is high ({value:.1f}%).")

        return {
            "status": "CRITICAL" if critical else "WARNING" if warnings else "NORMAL",
            "warnings": warnings,
            "automatic_actions": False,
        }

    def get_overview(self) -> Dict[str, object]:
        """Keep the original limit summary available to existing callers."""
        return {
            "cpu_limit": self.cpu_limit,
            "ram_limit": self.ram_limit,
            "status": "monitoring",
        }
