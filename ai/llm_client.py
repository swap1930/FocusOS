"""AI client wrapper for natural-language assistance."""


class LLMClient:
    """Small wrapper around the LLM integration used by the terminal."""

    def __init__(self, endpoint: str = "local"):
        self.endpoint = endpoint

    def generate(self, prompt: str):
        """Generate a response for the given prompt."""
        return {"prompt": prompt, "status": "stubbed"}
