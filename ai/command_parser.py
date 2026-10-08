"""Natural-language command parsing for FocusOS."""


class CommandParser:
    """Converts user prompts into FocusOS actions."""

    def parse(self, prompt: str):
        """Return a normalized command intent."""
        return {"raw_prompt": prompt, "action": "focus"}
