"""Focus engine responsible for identifying the active task and focus context."""

from __future__ import annotations

from typing import Dict, Optional


class FocusEngine:
    """Detect active application state, task mode, and focus priority."""

    FOCUS_PATTERNS = {
        "ml_training": ("pytorch", "tensorflow", "jupyter", "ml", "training", "notebook"),
        "coding": ("vscode", "code", "pycharm", "intellij", "python", "notepad++", "editor"),
        "browsing": ("chrome", "edge", "firefox", "browser", "safari", "web"),
        "rendering": ("blender", "maya", "cinema", "render", "after effects", "premiere"),
        "presentation": ("powerpoint", "slides", "keynote", "present"),
        "communication": ("slack", "teams", "discord", "telegram", "zoom"),
    }

    def __init__(self, app_name: Optional[str] = None, window_title: Optional[str] = None):
        self.active_app = app_name
        self.active_window = window_title
        self.user_activity = "active"
        self.focus_mode = "idle"
        self.focus_score = 0
        self.task_history = []

    def detect_active_application(self):
        """Return the currently active application name."""
        return self.active_app

    def detect_active_window(self):
        """Return the active window title if available."""
        return self.active_window

    def classify_task(self, app_name: Optional[str] = None, window_title: Optional[str] = None) -> str:
        """Map an application or window to a focus task category."""
        app_text = (app_name or self.active_app or "").strip()
        window_text = (window_title or self.active_window or "").strip()
        combined_text = f"{app_text} {window_text}".lower()

        if not combined_text:
            self.focus_mode = "idle"
            return self.focus_mode

        for mode, keywords in self.FOCUS_PATTERNS.items():
            if any(keyword in combined_text for keyword in keywords):
                self.focus_mode = mode
                return mode

        self.focus_mode = "idle"
        return self.focus_mode

    def detect_current_task(self, app_name: Optional[str] = None, window_title: Optional[str] = None) -> str:
        """Compatibility wrapper for task detection."""
        return self.classify_task(app_name, window_title)

    def compute_focus_score(
        self,
        app_name: Optional[str] = None,
        window_title: Optional[str] = None,
        user_activity: Optional[str] = None,
    ) -> int:
        """Compute a 0-100 focus score from the active app and user state."""
        app_text = (app_name or self.active_app or "").strip()
        window_text = (window_title or self.active_window or "").strip()
        activity = (user_activity or self.user_activity or "active").lower()

        score = 30
        if app_text:
            score += 25
        if window_text:
            score += 15

        task = self.classify_task(app_text, window_text)
        if task != "idle":
            score += 20

        if activity in {"idle", "inactive", "away"}:
            score -= 25
        elif activity == "active":
            score += 10

        score = max(0, min(100, score))
        self.focus_score = score
        return self.focus_score

    def snapshot(self) -> Dict[str, object]:
        """Return a serializable view of the engine's current state."""
        return {
            "status": "monitoring",
            "active_application": self.active_app,
            "active_window": self.active_window,
            "focus_mode": self.focus_mode,
            "focus_score": self.focus_score,
            "user_activity": self.user_activity,
        }

    def update_focus(
        self,
        app_name: Optional[str],
        window_title: Optional[str] = None,
        user_activity: Optional[str] = None,
    ) -> Dict[str, object]:
        """Update the active task state and return a focus snapshot."""
        if app_name is not None:
            self.active_app = app_name
        if window_title is not None:
            self.active_window = window_title
        if user_activity is not None:
            self.user_activity = user_activity

        self.focus_mode = self.classify_task(self.active_app, self.active_window)
        self.focus_score = self.compute_focus_score(self.active_app, self.active_window, self.user_activity)
        self.task_history.append(
            {
                "active_application": self.active_app,
                "active_window": self.active_window,
                "focus_mode": self.focus_mode,
                "focus_score": self.focus_score,
                "user_activity": self.user_activity,
            }
        )
        return self.snapshot()
