"""Read-only system and foreground-window monitoring."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from typing import Dict, List, Optional
from ctypes import wintypes

import psutil

from core.gnome_focus import ensure_extension_enabled, get_active_window as get_gnome_active_window
from core.gnome_focus import is_gnome_wayland


class SystemMonitor:
    """Collect CPU, memory, process, and active-window information."""

    _gnome_setup_checked = False
    _gnome_setup_warning: Optional[str] = None

    def collect(self) -> Dict[str, object]:
        """Return a single current system snapshot."""
        active_window = self.get_active_window()
        processes: List[Dict[str, object]] = []

        for process in psutil.process_iter(["pid", "name", "create_time", "ppid"]):
            try:
                info = process.info
                cpu_percent = process.cpu_percent(interval=None)
                memory_percent = process.memory_percent()
                memory_rss = process.memory_info().rss
            except psutil.Error:
                continue

            try:
                io_counters = process.io_counters()
                read_bytes = io_counters.read_bytes
                write_bytes = io_counters.write_bytes
            except (psutil.Error, NotImplementedError, AttributeError):
                read_bytes = None
                write_bytes = None

            processes.append(
                {
                    "pid": info["pid"],
                    "name": info["name"] or "",
                    "ppid": info["ppid"],
                    "create_time": info["create_time"],
                    "cpu_percent": cpu_percent,
                    "memory_percent": memory_percent,
                    "memory_rss": memory_rss,
                    "read_bytes": read_bytes,
                    "write_bytes": write_bytes,
                }
            )

        system_drive = os.environ.get("SystemDrive")
        disk_path = f"{system_drive}{os.sep}" if system_drive else os.path.abspath(os.sep)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(disk_path)
        return {
            "cpu_usage": psutil.cpu_percent(interval=None),
            "ram_usage": memory.percent,
            "ram_available_bytes": memory.available,
            "ram_total_bytes": memory.total,
            "disk_usage": disk.percent,
            "disk_free_bytes": disk.free,
            "disk_total_bytes": disk.total,
            "gpu_usage": self._get_gpu_usage(),
            "active_window": active_window,
            "processes": processes,
        }

    def get_active_window_pid(self) -> Optional[int]:
        """Return the current foreground process ID for last-moment safety checks."""
        pid = self.get_active_window().get("pid")
        return pid if isinstance(pid, int) else None

    def get_active_window(self) -> Dict[str, object]:
        """Read the foreground window and owning process."""
        return self._get_active_window()

    @staticmethod
    def _get_gpu_usage() -> Optional[float]:
        """Read aggregate GPU utilization when the NVIDIA utility is available."""
        nvidia_smi = shutil.which("nvidia-smi")
        if nvidia_smi is None:
            return None

        try:
            result = subprocess.run(
                [
                    nvidia_smi,
                    "--query-gpu=utilization.gpu",
                    "--format=csv,noheader,nounits",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            return None

        values = []
        for line in result.stdout.splitlines():
            try:
                values.append(float(line.strip()))
            except ValueError:
                continue
        return sum(values) / len(values) if values else None

    @staticmethod
    def _get_active_window() -> Dict[str, object]:
        """Read the foreground window using the supported desktop backend."""
        if sys.platform.startswith("linux"):
            return SystemMonitor._get_linux_active_window()
        if os.name != "nt":
            return {"application": None, "title": None, "pid": None}

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

    @staticmethod
    def _get_linux_active_window() -> Dict[str, object]:
        """Read X11 focus with xdotool; do not guess focus under Wayland."""
        if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
            if is_gnome_wayland():
                if not SystemMonitor._gnome_setup_checked:
                    SystemMonitor._gnome_setup_warning = ensure_extension_enabled()
                    SystemMonitor._gnome_setup_checked = True
                if SystemMonitor._gnome_setup_warning:
                    return {
                        "application": None,
                        "title": None,
                        "pid": None,
                        "warning": SystemMonitor._gnome_setup_warning,
                    }
                return get_gnome_active_window()
            return {
                "application": None,
                "title": None,
                "pid": None,
                "warning": "Active-window detection is unavailable in this Wayland session.",
            }
        if not os.environ.get("DISPLAY"):
            return {
                "application": None,
                "title": None,
                "pid": None,
                "warning": "No X11 display was detected; active-window detection is unavailable.",
            }

        xdotool = shutil.which("xdotool")
        if xdotool is None:
            return {
                "application": None,
                "title": None,
                "pid": None,
                "warning": "Install xdotool to enable active-window detection in X11.",
            }
        try:
            window_result = subprocess.run(
                [xdotool, "getwindowfocus"],
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            )
            window_id = window_result.stdout.strip()
            if not window_id:
                raise ValueError("xdotool returned an empty focused window ID")
            pid_result = subprocess.run(
                [xdotool, "getwindowpid", window_id],
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            )
            title_result = subprocess.run(
                [xdotool, "getwindowname", window_id],
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            )
            pid = int(pid_result.stdout.strip())
            process = psutil.Process(pid)
            return {
                "application": process.name(),
                "title": title_result.stdout.strip() or None,
                "pid": pid,
                "warning": None,
            }
        except (OSError, ValueError, psutil.Error, subprocess.SubprocessError) as error:
            return {
                "application": None,
                "title": None,
                "pid": None,
                "warning": f"Could not detect the active X11 window: {error}",
            }
