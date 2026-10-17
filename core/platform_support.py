"""Runtime platform detection for FocusOS."""

from __future__ import annotations

import os
import sys


def is_windows() -> bool:
    return os.name == "nt"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def supports_admin_restart() -> bool:
    return is_windows()
