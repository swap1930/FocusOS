"""Read-only system and foreground-window monitoring."""

from __future__ import annotations

import ctypes
import os
from typing import Dict, List, Optional
from ctypes import wintypes

import psutil


class SystemMonitor:
    """Collect CPU, memory, process, and active-window information."""

    def collect(self) -> Dict[str, object]:
        """Return a single current system snapshot."""
        active_window = self._get_active_window()
        processes: List[Dict[str, object]] = []

        for process in psutil.process_iter(["pid", "name"]):
            try:
                info = process.info
                cpu_percent = process.cpu_percent(interval=None)
            except psutil.Error:
                continue

            processes.append(
                {
                    "pid": info["pid"],
                    "name": info["name"] or "",
                    "cpu_percent": cpu_percent,
                }
            )

        return {
            "cpu_usage": psutil.cpu_percent(interval=None),
            "ram_usage": psutil.virtual_memory().percent,
            "gpu_usage": None,
            "active_window": active_window,
            "processes": processes,
        }

    @staticmethod
    def _get_active_window() -> Dict[str, object]:
        """Read the foreground window using Windows APIs."""
        if os.name != "nt":
            raise OSError("Foreground-window detection is currently supported on Windows only.")

        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return {"application": None, "title": None, "pid": None}

        title_length = user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))

        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        pid: Optional[int] = process_id.value or None

        application: Optional[str] = None
        if pid is not None:
            try:
                application = psutil.Process(pid).name()
            except psutil.Error:
                application = None

        return {
            "application": application,
            "title": title_buffer.value or None,
            "pid": pid,
        }
