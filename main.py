"""Entry point for the FocusOS prototype."""

import time

from api.focus_api import FocusAPI

api = FocusAPI()
app = api.create_app()


def main():
    """Start FocusOS and continuously display its current state in the terminal."""
    api.runtime.start()
    print("FocusOS is monitoring your system. Press Ctrl+C to stop.\n")

    try:
        while True:
            state = api.get_state()
            print(
                f"\r{state['status']} | "
                f"App: {state['focus_application'] or 'Unknown'} | "
                f"Mode: {state['focus_mode']} | "
                f"Focus: {state['focus_score']}% | "
                f"CPU: {state['cpu_usage']}% | "
                f"RAM: {state['ram_usage']}% | "
                f"Processes: {state['active_processes']} active, "
                f"{state['background_processes']} background",
                end="",
                flush=True,
            )
            time.sleep(2)
    except KeyboardInterrupt:
        api.runtime.stop()
        print("\nFocusOS monitoring stopped.")


if __name__ == "__main__":
    main()
