"""Background process classification and lifecycle controls."""

from typing import Dict, List, Optional

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

    def build_priority_plan(
        self,
        processes: List[Dict[str, object]],
        focus_pid: Optional[int] = None,
    ) -> List[Dict[str, object]]:
        """Recommend priorities without applying OS-level process changes."""
        plan = []
        for process in processes:
            pid = process.get("pid")
            name = str(process.get("name", ""))
            cpu_usage = float(process.get("cpu_percent", 0.0))
            if focus_pid is not None and pid == focus_pid:
                classification = "active"
                priority = "high"
            else:
                classification = self.classify(name, cpu_usage)
                priority = (
                    "high"
                    if classification == "active"
                    else "low"
                    if classification == "background"
                    else "normal"
                )

            plan.append(
                {
                    "pid": pid,
                    "name": name,
                    "cpu_percent": cpu_usage,
                    "classification": classification,
                    "recommended_priority": priority,
                    "applied": False,
                }
            )
        return plan
