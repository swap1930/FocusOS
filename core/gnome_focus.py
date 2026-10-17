"""GNOME Wayland active-window integration."""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional


EXTENSION_UUID = "focusos@focusos.local"
BUS_NAME = "org.focusos.Focus"
OBJECT_PATH = "/org/focusos/Focus"
DBUS_METHOD = "org.focusos.Focus.GetActiveWindow"


def is_gnome_wayland() -> bool:
    desktop = ":".join(
        (
            os.environ.get("XDG_CURRENT_DESKTOP", ""),
            os.environ.get("XDG_SESSION_DESKTOP", ""),
            os.environ.get("DESKTOP_SESSION", ""),
        )
    ).casefold()
    return bool(
        (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland")
        and "gnome" in desktop
    )


def _extension_source() -> Path:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return bundle_root / "extensions" / EXTENSION_UUID


def ensure_extension_enabled() -> Optional[str]:
    """Install and enable FocusOS's own GNOME extension for the current user."""
    extension_cli = shutil.which("gnome-extensions")
    if extension_cli is None:
        return "GNOME Wayland focus needs the gnome-extensions command."

    source = _extension_source()
    if not (source / "metadata.json").is_file() or not (source / "extension.js").is_file():
        return "FocusOS GNOME focus-extension files are missing from this installation."

    destination = (
        Path.home()
        / ".local"
        / "share"
        / "gnome-shell"
        / "extensions"
        / EXTENSION_UUID
    )
    try:
        destination.mkdir(parents=True, exist_ok=True)
        for filename in ("metadata.json", "extension.js"):
            source_file = source / filename
            destination_file = destination / filename
            content = source_file.read_bytes()
            if not destination_file.is_file() or destination_file.read_bytes() != content:
                destination_file.write_bytes(content)
        result = subprocess.run(
            [extension_cli, "enable", EXTENSION_UUID],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return f"Could not enable FocusOS GNOME focus integration: {error}"

    if result.returncode:
        details = result.stderr.strip() or result.stdout.strip()
        return (
            "Could not enable the FocusOS GNOME extension"
            + (f": {details}" if details else ".")
        )
    return None


def get_active_window() -> Dict[str, object]:
    """Fetch active-window information from the local GNOME Shell extension."""
    gdbus = shutil.which("gdbus")
    if gdbus is None:
        return {
            "application": None,
            "title": None,
            "pid": None,
            "warning": "GNOME Wayland focus needs the gdbus command.",
        }

    try:
        result = subprocess.run(
            [
                gdbus,
                "call",
                "--session",
                "--dest",
                BUS_NAME,
                "--object-path",
                OBJECT_PATH,
                "--method",
                DBUS_METHOD,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        variant = ast.literal_eval(result.stdout.strip())
        if not isinstance(variant, tuple) or len(variant) != 1 or not isinstance(variant[0], str):
            raise ValueError("GNOME focus service returned an invalid D-Bus response")
        state = json.loads(variant[0])
        if not isinstance(state, dict):
            raise ValueError("GNOME focus service returned an invalid window record")
        pid = state.get("pid")
        application = state.get("application")
        title = state.get("title")
        if pid is not None and (not isinstance(pid, int) or pid <= 0):
            raise ValueError("GNOME focus service returned an invalid process ID")
        if application is not None and not isinstance(application, str):
            raise ValueError("GNOME focus service returned an invalid application name")
        if title is not None and not isinstance(title, str):
            raise ValueError("GNOME focus service returned an invalid window title")
        return {
            "application": application,
            "title": title,
            "pid": pid,
            "warning": state.get("warning"),
        }
    except (OSError, ValueError, SyntaxError, subprocess.SubprocessError) as error:
        return {
            "application": None,
            "title": None,
            "pid": None,
            "warning": f"GNOME Wayland focus integration is unavailable: {error}",
        }
