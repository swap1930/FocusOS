"""Entry point for the FocusOS prototype."""

from api.focus_api import FocusAPI
from core.focus_engine import FocusEngine


def main():
    """Start the initial FocusOS prototype runtime."""
    api = FocusAPI()
    engine = FocusEngine()
    print(f"{api.healthcheck()['status']} | {engine.detect_active_application()}")


if __name__ == "__main__":
    main()
