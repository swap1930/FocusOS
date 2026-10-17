"""Explicit Windows elevation helpers for FocusOS."""

from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

import psutil

from core.platform_support import supports_admin_restart

def is_user_admin() -> bool:
    """Return whether the current process has an elevated Windows token."""
    if not supports_admin_restart():
        return False
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def _shell_execute_runas(executable: str, parameters: str, cwd: str) -> int:
    return int(
        ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            executable,
            parameters,
            cwd,
            1,
        )
    )


def request_elevated_restart(
    arguments: Sequence[str],
    wait_for_pid: int,
) -> Optional[str]:
    """Request a UAC-approved restart that waits for this process to exit."""
    if not supports_admin_restart():
        return "Administrator restart is supported on Windows only."

    command_arguments = [*arguments, "--wait-for-process", str(wait_for_pid)]
    try:
        result = _shell_execute_runas(
            sys.executable,
            subprocess.list2cmdline(command_arguments),
            str(Path.cwd()),
        )
    except OSError as error:
        return f"Windows could not request an administrator restart: {error}"

    if result == 1223:
        return "Administrator restart was cancelled; FocusOS is still running normally."
    if result == 5:
        return "Administrator restart was cancelled or denied; FocusOS is still running normally."
    if result > 32:
        return None
    return f"Windows could not start the administrator restart (error {result})."


def wait_for_process_exit(pid: int) -> None:
    """Wait for the previous FocusOS process to exit before starting a new one."""
    try:
        psutil.Process(pid).wait()
    except psutil.NoSuchProcess:
        return
    except psutil.Error as error:
        raise RuntimeError(
            f"Could not safely wait for the previous FocusOS process {pid}: {error}"
        ) from error
