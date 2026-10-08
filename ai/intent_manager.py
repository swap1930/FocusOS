"""Intent routing between user requests and FocusOS actions."""


class IntentManager:
    """Maps request intent to a safe system operation."""

    def resolve(self, prompt: str):
        """Return a safe command mapping."""
        return {"intent": "focus_mode", "prompt": prompt}
