"""Background process classification and lifecycle controls."""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import c_size_t, c_ssize_t, c_void_p, wintypes
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import psutil

from core.platform_support import is_linux, is_windows


ProcessIdentity = Tuple[int, Optional[float]]


class _LinuxIOVec(ctypes.Structure):
    _fields_ = [("base", c_void_p), ("length", c_size_t)]


class ProcessManager:
    """Classify processes and safely manage explicitly allowlisted applications."""

    _PROTECTED_NAMES = {
        "csrss.exe",
        "dwm.exe",
        "explorer.exe",
        "fontdrvhost.exe",
        "lsass.exe",
        "runtimebroker.exe",
        "services.exe",
        "smss.exe",
        "spoolsv.exe",
        "system",
        "system idle process",
        "svchost.exe",
        "wininit.exe",
        "winlogon.exe",
        "taskhostw.exe",
        "conhost.exe",
        "dllhost.exe",
        "systemd",
        "dbus-daemon",
        "dbus-broker",
        "pipewire",
        "wireplumber",
        "pulseaudio",
        "gnome-shell",
        "kwin_wayland",
        "plasmashell",
        "xorg",
        "xwayland",
        "sway",
        "weston",
        "wayfire",
        "sshd",
        "gdm",
        "sddm",
    }

    def __init__(
        self,
        allowlist: Iterable[str] = (),
        suspend_after_seconds: float = 300,
        clock: Callable[[], float] = time.monotonic,
        process_factory: Callable[[int], psutil.Process] = psutil.Process,
        active_pid_provider: Optional[Callable[[], Optional[int]]] = None,
        selected_instances: Iterable[ProcessIdentity] = (),
        working_set_trimmer: Optional[Callable[[int], Tuple[int, Optional[str]]]] = None,
    ):
        self.allowlist = {os.path.basename(name).casefold() for name in allowlist}
        self.suspend_after_seconds = suspend_after_seconds
        self.auto_optimize_user_processes = False
        # When True the focused process is boosted to HIGH_PRIORITY_CLASS instead
        # of the default ABOVE_NORMAL_PRIORITY_CLASS – activated by ML Power Mode.
        self.ml_power_mode = False
        self._ml_memory_trim_after_seconds: Optional[float] = None
        self._clock = clock
        self._process_factory = process_factory
        self._active_pid_provider = active_pid_provider
        self.selected_instances = set(selected_instances)
        self._working_set_trimmer = working_set_trimmer or self._trim_working_set
        self._current_user = psutil.Process().username()
        self._protected_pids = {os.getpid()}
        self._protection_error: Optional[str] = None
        try:
            self._protected_pids.update(parent.pid for parent in psutil.Process().parents())
        except psutil.Error as error:
            self._protection_error = str(error)
        self._background_since: Dict[ProcessIdentity, float] = {}
        self._suspended: Dict[ProcessIdentity, Tuple[psutil.Process, str]] = {}
        self._original_priorities: Dict[ProcessIdentity, Tuple[psutil.Process, object]] = {}
        self._original_schedulers: Dict[
            ProcessIdentity, Tuple[psutil.Process, int, os.sched_param]
        ] = {}
        self._linux_scheduler_attempted: set[ProcessIdentity] = set()
        self._trimmed_instances: set[ProcessIdentity] = set()
        self.working_set_trimmed_bytes = 0
        self.action_errors: List[str] = []

    def classify(self, process_name: str, cpu_usage: float = 0.0) -> str:
        """Return a priority categorization for a process."""
        if cpu_usage > 50:
            return "active"
        if process_name.lower().startswith("chrome"):
            return "background"
        return "idle"

    def build_priority_plan(
        self,
        processes: List[Dict[str, object]],
        focus_pid: Optional[int] = None,
        apply_controls: bool = True,
    ) -> List[Dict[str, object]]:
        """Recommend priorities and apply configured controls to safe processes."""
        self.action_errors = []
        now = self._clock()
        global_focus_verified = False
        if apply_controls and self.auto_optimize_user_processes:
            if focus_pid is not None and self._active_pid_provider is not None:
                try:
                    global_focus_verified = self._active_pid_provider() == focus_pid
                except (OSError, psutil.Error) as error:
                    self._record_error("foreground", error)
        process_by_pid = {item.get("pid"): item for item in processes}
        focused_process = process_by_pid.get(focus_pid)
        focused_name = (
            os.path.basename(str(focused_process.get("name", ""))).casefold()
            if focused_process
            else ""
        )
        focused_allowlisted_name = focused_name if focused_name in self.allowlist else ""
        ml_target_pids = (
            self._get_process_family_pids(focus_pid, processes)
            if self.ml_power_mode
            else set()
        )

        seen: set[ProcessIdentity] = set()
        plan = []

        for process in processes:
            pid = process.get("pid")
            name = str(process.get("name", ""))
            normalized_name = os.path.basename(name).casefold()
            cpu_usage = float(process.get("cpu_percent", 0.0))
            create_time = process.get("create_time")
            identity = (pid, create_time) if isinstance(pid, int) else (-1, None)
            seen.add(identity)
            is_focused = pid == focus_pid
            is_related = pid in ml_target_pids
            is_allowlisted_app = normalized_name in self.allowlist
            is_selected_instance = identity in self.selected_instances
            is_focused_app = (
                bool(focused_allowlisted_name and normalized_name == focused_name)
                or (is_selected_instance and is_focused)
            )
            is_priority_target = is_focused or is_related
            was_ml_target = (
                self.ml_power_mode
                and identity in self._original_priorities
                and not is_priority_target
            )

            if is_priority_target:
                classification = "active"
                priority = "high"
            else:
                classification = self.classify(name, cpu_usage)
                priority = (
                    "high"
                    if classification == "active"
                    else "low"
                    if classification == "background"
                    else "normal"
                )

            action_error = None
            suspended = identity in self._suspended
            background_seconds = 0.0
            is_protected_name = normalized_name in self._PROTECTED_NAMES
            if (
                apply_controls
                and (is_allowlisted_app or is_selected_instance)
                and not is_protected_name
            ):
                if is_focused_app:
                    self._background_since.pop(identity, None)
                    self._trimmed_instances.discard(identity)
                    if is_allowlisted_app:
                        for suspended_identity, (_, suspended_name) in list(self._suspended.items()):
                            if suspended_name == normalized_name:
                                action_error = self._resume(suspended_identity) or action_error
                    else:
                        action_error = self._resume(identity) or action_error
                    suspended = identity in self._suspended
                    if is_focused and (is_allowlisted_app or is_selected_instance):
                        action_error = self._boost_priority(identity, pid) or action_error
                    else:
                        action_error = self._restore_priority(identity) or action_error
                elif not is_focused:
                    if is_allowlisted_app or identity in self._original_priorities:
                        action_error = self._restore_priority(identity) or action_error
                    started = self._background_since.setdefault(identity, now)
                    background_seconds = max(0.0, now - started)
                    if background_seconds >= self.suspend_after_seconds and not suspended:
                        action_error = self._suspend(identity, pid, normalized_name)
                        suspended = identity in self._suspended
            elif apply_controls and was_ml_target:
                action_error = self._restore_priority(identity) or action_error
                action_error = self._restore_linux_scheduler(identity) or action_error
            elif (
                apply_controls
                and self.auto_optimize_user_processes
                and global_focus_verified
                and not is_protected_name
            ):
                if is_windows() and is_priority_target:
                    self._background_since.pop(identity, None)
                    self._trimmed_instances.discard(identity)
                    action_error = self._resume(identity) or action_error
                    action_error = self._restore_priority(identity) or action_error
                    boost_class = (
                        psutil.HIGH_PRIORITY_CLASS
                        if self.ml_power_mode
                        else psutil.ABOVE_NORMAL_PRIORITY_CLASS
                    )
                    action_error = self._boost_priority(
                        identity, pid, boost_class
                    ) or action_error
                elif is_windows():
                    action_error = self._restore_priority(identity) or action_error
                    action_error = self._lower_priority(identity, pid) or action_error
                    started = self._background_since.setdefault(identity, now)
                    background_seconds = max(0.0, now - started)
                    trim_delay = (
                        min(self.suspend_after_seconds, self._ml_memory_trim_after_seconds)
                        if self.ml_power_mode and self._ml_memory_trim_after_seconds is not None
                        else self.suspend_after_seconds
                    )
                    if (
                        background_seconds >= trim_delay
                        and identity not in self._trimmed_instances
                    ):
                        try:
                            active_pid = (
                                self._active_pid_provider()
                                if self._active_pid_provider is not None
                                else None
                            )
                        except (OSError, psutil.Error) as error:
                            self._record_error("foreground", error)
                            active_pid = None
                        if active_pid != focus_pid or active_pid == pid:
                            action_error = (
                                f"Skipped working-set trim for PID {pid}: "
                                "foreground app changed or could not be verified."
                            )
                            self.action_errors.append(action_error)
                        elif self._get_safe_process(identity, normalized_name) is not None:
                            try:
                                trimmed_bytes, warning = self._working_set_trimmer(
                                    int(pid)
                                )
                            except (OSError, psutil.Error) as error:
                                trimmed_bytes = 0
                                warning = f"Could not trim PID {pid}'s working set: {error}"
                            self.working_set_trimmed_bytes += max(0, trimmed_bytes)
                            self._trimmed_instances.add(identity)
                            if warning:
                                action_error = warning
                                self.action_errors.append(warning)
                elif is_linux() and is_priority_target:
                    self._background_since.pop(identity, None)
                    self._trimmed_instances.discard(identity)
                    self._linux_scheduler_attempted.discard(identity)
                    action_error = self._resume(identity) or action_error
                    action_error = self._restore_priority(identity) or action_error
                    action_error = self._restore_linux_scheduler(identity) or action_error
                    if self.ml_power_mode:
                        action_error = self._boost_linux_priority(identity, pid) or action_error
                elif is_linux():
                    started = self._background_since.setdefault(identity, now)
                    background_seconds = max(0.0, now - started)
                    action_error = self._lower_linux_scheduler(identity, pid) or action_error
                    trim_delay = (
                        min(self.suspend_after_seconds, self._ml_memory_trim_after_seconds)
                        if self.ml_power_mode and self._ml_memory_trim_after_seconds is not None
                        else self.suspend_after_seconds
                    )
                    if (
                        background_seconds >= trim_delay
                        and identity not in self._trimmed_instances
                    ):
                        try:
                            active_pid = (
                                self._active_pid_provider()
                                if self._active_pid_provider is not None
                                else None
                            )
                        except (OSError, psutil.Error) as error:
                            self._record_error("foreground", error)
                            active_pid = None
                        if active_pid != focus_pid or active_pid == pid:
                            action_error = (
                                f"Skipped memory page-out for PID {pid}: "
                                "foreground app changed or could not be verified."
                            )
                            self.action_errors.append(action_error)
                        elif self._get_safe_process(identity, normalized_name) is not None:
                            trimmed_bytes, warning = self._working_set_trimmer(int(pid))
                            self.working_set_trimmed_bytes += max(0, trimmed_bytes)
                            self._trimmed_instances.add(identity)
                            if warning:
                                action_error = warning
                                self.action_errors.append(warning)
            else:
                self._background_since.pop(identity, None)
                action_error = self._resume(identity) or action_error
                action_error = self._restore_priority(identity) or action_error
                action_error = self._restore_linux_scheduler(identity) or action_error
                self._linux_scheduler_attempted.discard(identity)
                self._trimmed_instances.discard(identity)
                suspended = identity in self._suspended

            plan.append(
                {
                    "pid": pid,
                    "name": name,
                    "cpu_percent": cpu_usage,
                    "memory_percent": float(process.get("memory_percent", 0.0)),
                    "memory_rss": int(process.get("memory_rss", 0)),
                    "read_bytes": process.get("read_bytes"),
                    "write_bytes": process.get("write_bytes"),
                    "classification": classification,
                    "recommended_priority": priority,
                    "applied": (
                        identity in self._original_priorities
                        or identity in self._original_schedulers
                        or identity in self._suspended
                    ),
                    "suspended": suspended,
                    "background_seconds": round(background_seconds, 1),
                    "allowlisted": is_allowlisted_app,
                    "selected_for_auto_suspend": is_selected_instance,
                    "action_error": action_error,
                }
            )

        for identity in list(self._background_since):
            if identity not in seen:
                self._background_since.pop(identity, None)
        self._trimmed_instances.intersection_update(seen)
        self.selected_instances.intersection_update(seen)
        self._linux_scheduler_attempted.intersection_update(seen)
        for identity in list(self._suspended):
            if identity not in seen:
                self._resume(identity)
        for identity in list(self._original_priorities):
            if identity not in seen:
                self._restore_priority(identity)
        for identity in list(self._original_schedulers):
            if identity not in seen:
                self._restore_linux_scheduler(identity)

        return plan

    @staticmethod
    def _get_process_family_pids(
        focus_pid: Optional[int],
        processes: List[Dict[str, object]],
    ) -> set[int]:
        """Return a selected process and its descendants from the current snapshot."""
        if not isinstance(focus_pid, int):
            return set()
        family = {focus_pid}
        changed = True
        while changed:
            changed = False
            for item in processes:
                pid = item.get("pid")
                parent_pid = item.get("ppid")
                if isinstance(pid, int) and isinstance(parent_pid, int):
                    if parent_pid in family and pid not in family:
                        family.add(pid)
                        changed = True
        return family

    def restore_all(self) -> List[str]:
        """Resume processes and restore priorities changed by this manager."""
        self.action_errors = []
        for identity in list(self._suspended):
            self._resume(identity)
        for identity in list(self._original_priorities):
            self._restore_priority(identity)
        for identity in list(self._original_schedulers):
            self._restore_linux_scheduler(identity)
        self._background_since.clear()
        self._trimmed_instances.clear()
        self._linux_scheduler_attempted.clear()
        self._ml_memory_trim_after_seconds = None
        return list(self.action_errors)

    def list_suspend_candidates(
        self,
        processes: List[Dict[str, object]],
        active_pid: Optional[int],
    ) -> List[Dict[str, object]]:
        """List current-user, non-system processes other than the foreground app."""
        if active_pid is None:
            return []

        candidates = []
        for item in processes:
            pid = item.get("pid")
            name = os.path.basename(str(item.get("name", "")))
            create_time = item.get("create_time")
            if (
                not isinstance(pid, int)
                or pid == active_pid
                or pid <= 4
                or name.casefold() in self._PROTECTED_NAMES
                or not isinstance(create_time, (int, float))
            ):
                continue
            process = self._get_safe_process((pid, float(create_time)), name.casefold())
            if process is None:
                continue
            candidates.append(
                {
                    "pid": pid,
                    "name": name,
                    "create_time": float(create_time),
                    "memory_rss": int(item.get("memory_rss", 0)),
                    "memory_mb": round(int(item.get("memory_rss", 0)) / (1024 * 1024), 1),
                }
            )
        candidates.sort(key=lambda item: int(item["memory_rss"]), reverse=True)
        return candidates

    def suspend_selected_process(
        self,
        pid: int,
        create_time: float,
        name: str,
    ) -> Tuple[int, Optional[str]]:
        """Suspend one selected background process and trim its working set on Windows."""
        if self._active_pid_provider is None:
            raise RuntimeError("Cannot verify foreground app; refusing to suspend a process.")
        identity = (pid, create_time)
        if os.path.basename(name).casefold() in self._PROTECTED_NAMES:
            raise RuntimeError("System and protected processes cannot be suspended.")
        active_pid = self._active_pid_provider()
        if active_pid is None:
            raise RuntimeError("Cannot verify foreground app; refusing to suspend a process.")
        if active_pid == pid:
            raise RuntimeError("That process is currently in the foreground.")
        process = self._get_safe_process(identity, os.path.basename(name).casefold())
        if process is None:
            raise RuntimeError(f"PID {pid} is no longer eligible for suspension.")
        if self._active_pid_provider() != active_pid:
            raise RuntimeError("Foreground app changed during the safety check; retry selection.")
        if self._active_pid_provider() == pid:
            raise RuntimeError("That process became foreground; refusing to suspend it.")
        try:
            process.suspend()
        except psutil.Error as error:
            self._record_error(pid, error)
            raise RuntimeError(f"Could not suspend PID {pid}: {error}") from error
        self._suspended[identity] = (process, os.path.basename(name).casefold())
        try:
            trimmed_bytes, warning = self._working_set_trimmer(pid)
        except (OSError, psutil.Error) as error:
            trimmed_bytes = 0
            warning = f"Suspended PID {pid}, but working-set trimming failed: {error}"
        self.working_set_trimmed_bytes += max(0, trimmed_bytes)
        return trimmed_bytes, warning

    @staticmethod
    def _trim_working_set(pid: int) -> Tuple[int, Optional[str]]:
        """Ask Windows to evict this selected process's resident pages where possible."""
        if is_linux():
            return ProcessManager._page_out_linux_working_set(pid)
        if os.name != "nt":
            return 0, "Working-set trimming is supported on Windows only."

        handle = None
        try:
            process = psutil.Process(pid)
            before_bytes = process.memory_info().rss
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            open_process = kernel32.OpenProcess
            open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            open_process.restype = wintypes.HANDLE
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = [wintypes.HANDLE]
            close_handle.restype = wintypes.BOOL
            empty_working_set = psapi.EmptyWorkingSet
            empty_working_set.argtypes = [wintypes.HANDLE]
            empty_working_set.restype = wintypes.BOOL

            handle = open_process(0x0100 | 0x0400, False, pid)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            if not empty_working_set(handle):
                raise ctypes.WinError(ctypes.get_last_error())
            after_bytes = psutil.Process(pid).memory_info().rss
            return max(0, before_bytes - after_bytes), None
        except (OSError, psutil.Error) as error:
            warning = f"Suspended PID {pid}, but could not trim its working set: {error}"
            return 0, warning
        finally:
            if handle:
                close_handle(handle)

    @staticmethod
    def _page_out_linux_working_set(pid: int) -> Tuple[int, Optional[str]]:
        """Request best-effort page-out for private mappings of one verified process."""
        if not hasattr(os, "pidfd_open"):
            return 0, "Linux working-set page-out requires kernel pidfd support."
        machine = os.uname().machine.casefold()
        syscall_number = {"x86_64": 440, "amd64": 440, "aarch64": 440, "arm64": 440}.get(
            machine
        )
        if syscall_number is None:
            return 0, f"Linux process page-out is unsupported on architecture {machine}."

        pidfd = None
        try:
            process = psutil.Process(pid)
            before_bytes = process.memory_info().rss
            pidfd = os.pidfd_open(pid)
            libc = ctypes.CDLL(None, use_errno=True)
            syscall = libc.syscall
            syscall.restype = c_ssize_t
            advised_bytes = 0
            max_advice_bytes = 64 * 1024 * 1024
            page_size = os.sysconf("SC_PAGE_SIZE")

            with open(f"/proc/{pid}/maps", encoding="utf-8") as maps_file:
                for line in maps_file:
                    columns = line.split(maxsplit=5)
                    if len(columns) < 2 or not columns[1].endswith("p") or "r" not in columns[1]:
                        continue
                    start_text, end_text = columns[0].split("-", maxsplit=1)
                    start = int(start_text, 16)
                    end = int(end_text, 16)
                    length = min(end - start, max_advice_bytes - advised_bytes)
                    length -= length % page_size
                    if length <= 0:
                        break

                    result = ProcessManager._advise_linux_pages(
                        syscall,
                        syscall_number,
                        pidfd,
                        start,
                        length,
                    )
                    if result < 0:
                        error_code = ctypes.get_errno()
                        raise OSError(error_code, os.strerror(error_code))
                    advised_bytes += result
                    if advised_bytes >= max_advice_bytes:
                        break

            after_bytes = psutil.Process(pid).memory_info().rss
            reclaimed_bytes = max(0, before_bytes - after_bytes)
            if advised_bytes == 0:
                return 0, (
                    f"Linux kernel did not page out memory for PID {pid}; "
                    "ptrace permissions or kernel support may be unavailable."
                )
            if reclaimed_bytes == 0:
                return 0, (
                    f"Kernel accepted {advised_bytes / (1024 * 1024):.1f} MB of page-out "
                    f"advice for PID {pid}, but no RSS reduction was measured."
                )
            return reclaimed_bytes, None
        except (OSError, ValueError, psutil.Error, AttributeError) as error:
            return 0, f"Could not page out memory for PID {pid}: {error}"
        finally:
            if pidfd is not None:
                os.close(pidfd)

    @staticmethod
    def _advise_linux_pages(
        syscall: Callable[..., int],
        syscall_number: int,
        pidfd: int,
        start: int,
        length: int,
    ) -> int:
        remote_iov = _LinuxIOVec(c_void_p(start), c_size_t(length))
        result = syscall(
            syscall_number,
            pidfd,
            ctypes.byref(remote_iov),
            c_size_t(1),
            21,
            0,
        )
        if result < 0:
            error_code = ctypes.get_errno()
            raise OSError(error_code, os.strerror(error_code))
        return int(result)

    def resume_selected_process(self, pid: int, create_time: float) -> Optional[str]:
        """Resume a process previously suspended through the manager."""
        return self._resume((pid, create_time))

    def selected_process_is_running(self, pid: int, create_time: float) -> bool:
        """Check whether the selected process instance is still running."""
        tracked = self._suspended.get((pid, create_time))
        if tracked is None:
            return False
        try:
            return tracked[0].is_running() and tracked[0].create_time() == create_time
        except psutil.NoSuchProcess:
            self._suspended.pop((pid, create_time), None)
            return False
        except psutil.Error as error:
            self._record_error(pid, error)
            raise RuntimeError(f"Could not verify suspended PID {pid}: {error}") from error

    @property
    def suspended_count(self) -> int:
        """Return the number of process instances still suspended by FocusOS."""
        return len(self._suspended)

    @property
    def selected_process_count(self) -> int:
        """Return the number of selected process instances still being monitored."""
        return len(self.selected_instances)

    def _get_safe_process(
        self,
        identity: ProcessIdentity,
        expected_name: Optional[str] = None,
    ) -> Optional[psutil.Process]:
        pid, expected_create_time = identity
        if self._protection_error is not None:
            message = f"Process safety check unavailable: {self._protection_error}"
            self.action_errors.append(message)
            return None
        if pid <= 4 or pid in self._protected_pids:
            return None

        try:
            process = self._process_factory(pid)
            if expected_create_time is not None and process.create_time() != expected_create_time:
                return None
            if process.username() != self._current_user:
                return None
            if expected_name and os.path.basename(process.name()).casefold() != expected_name:
                return None
        except psutil.NoSuchProcess:
            return None
        except psutil.Error as error:
            self._record_error(pid, error)
            return None
        return process

    def _suspend(self, identity: ProcessIdentity, pid: object, name: str) -> Optional[str]:
        if self._active_pid_provider is not None:
            try:
                active_pid = self._active_pid_provider()
            except (OSError, psutil.Error) as error:
                self._record_error(pid, error)
                return str(error)
            if active_pid is None:
                message = f"PID {pid}: skipped suspension because foreground process could not be verified"
                self.action_errors.append(message)
                return message
            if active_pid == identity[0]:
                return None

        process = self._get_safe_process(identity, name)
        if process is None:
            return None
        if self._active_pid_provider is not None:
            try:
                active_pid = self._active_pid_provider()
            except (OSError, psutil.Error) as error:
                self._record_error(pid, error)
                return str(error)
            if active_pid is None:
                message = f"PID {pid}: skipped suspension because foreground process could not be verified"
                self.action_errors.append(message)
                return message
            if active_pid == identity[0]:
                return None
        try:
            process.suspend()
        except psutil.NoSuchProcess:
            return None
        except psutil.Error as error:
            self._record_error(pid, error)
            return str(error)
        self._suspended[identity] = (process, name)
        try:
            trimmed_bytes, trim_warning = self._working_set_trimmer(int(pid))
        except (OSError, psutil.Error) as error:
            trimmed_bytes = 0
            trim_warning = f"Suspended PID {pid}, but working-set trimming failed: {error}"
        self.working_set_trimmed_bytes += max(0, trimmed_bytes)
        if trim_warning:
            self.action_errors.append(trim_warning)
        return trim_warning

    def _resume(self, identity: ProcessIdentity) -> Optional[str]:
        tracked = self._suspended.get(identity)
        if tracked is None:
            return None
        process, name = tracked
        safe_process = self._get_safe_process(identity, name)
        if safe_process is None:
            self._suspended.pop(identity, None)
            return None
        try:
            safe_process.resume()
        except psutil.NoSuchProcess:
            self._suspended.pop(identity, None)
            return None
        except psutil.Error as error:
            self._record_error(identity[0], error)
            return str(error)
        self._suspended.pop(identity, None)
        return None

    def _boost_linux_priority(
        self,
        identity: ProcessIdentity,
        pid: object,
    ) -> Optional[str]:
        """Apply a reversible nice adjustment without using privileged realtime priority."""
        if not is_linux() or identity in self._original_priorities:
            return None
        process = self._get_safe_process(identity)
        if process is None:
            return None
        try:
            original_nice = process.nice()
            process.nice(min(19, int(original_nice) + 5))
        except (psutil.NoSuchProcess, ProcessLookupError):
            return None
        except (psutil.Error, OSError) as error:
            self._record_error(pid, error)
            return str(error)
        self._original_priorities[identity] = (process, original_nice)
        return None

    def _boost_priority(
        self,
        identity: ProcessIdentity,
        pid: object,
        priority_class: int = psutil.HIGH_PRIORITY_CLASS,
    ) -> Optional[str]:
        if not is_windows():
            return None
        if identity in self._original_priorities:
            return None
        process = self._get_safe_process(identity)
        if process is None:
            return None
        try:
            original_priority = process.nice()
            process.nice(priority_class)
        except psutil.NoSuchProcess:
            return None
        except psutil.Error as error:
            self._record_error(pid, error)
            return str(error)
        self._original_priorities[identity] = (process, original_priority)
        return None

    def _lower_priority(self, identity: ProcessIdentity, pid: object) -> Optional[str]:
        if not is_windows():
            return None
        if identity in self._original_priorities:
            return None
        process = self._get_safe_process(identity)
        if process is None:
            return None
        try:
            original_priority = process.nice()
            process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        except psutil.NoSuchProcess:
            return None
        except psutil.Error as error:
            self._record_error(pid, error)
            return str(error)
        self._original_priorities[identity] = (process, original_priority)
        return None

    def _lower_linux_scheduler(
        self,
        identity: ProcessIdentity,
        pid: object,
    ) -> Optional[str]:
        if identity in self._original_schedulers or identity in self._linux_scheduler_attempted:
            return None
        self._linux_scheduler_attempted.add(identity)
        process = self._get_safe_process(identity)
        if process is None:
            self._linux_scheduler_attempted.discard(identity)
            return None
        if not hasattr(os, "SCHED_BATCH"):
            message = "Linux SCHED_BATCH is unavailable; CPU scheduling was not changed."
            self.action_errors.append(message)
            return message
        try:
            original_policy = os.sched_getscheduler(int(pid))
            original_param = os.sched_getparam(int(pid))
            if original_policy != os.SCHED_OTHER:
                message = (
                    f"PID {pid} uses a non-default scheduler; FocusOS left it unchanged "
                    "to preserve its scheduling policy."
                )
                self.action_errors.append(message)
                return message
            os.sched_setscheduler(
                int(pid),
                os.SCHED_BATCH,
                os.sched_param(original_param.sched_priority),
            )
        except (OSError, ValueError) as error:
            message = f"Could not set background CPU scheduling for PID {pid}: {error}"
            self.action_errors.append(message)
            return message
        self._original_schedulers[identity] = (
            process,
            original_policy,
            original_param,
        )
        return None

    def _restore_linux_scheduler(self, identity: ProcessIdentity) -> Optional[str]:
        tracked = self._original_schedulers.get(identity)
        if tracked is None:
            return None
        process, original_policy, original_param = tracked
        safe_process = self._get_safe_process(identity)
        if safe_process is None:
            self._original_schedulers.pop(identity, None)
            return None
        try:
            os.sched_setscheduler(
                identity[0],
                original_policy,
                os.sched_param(original_param.sched_priority),
            )
        except ProcessLookupError:
            self._original_schedulers.pop(identity, None)
            return None
        except (OSError, ValueError) as error:
            message = f"Could not restore CPU scheduling for PID {identity[0]}: {error}"
            self.action_errors.append(message)
            return message
        self._original_schedulers.pop(identity, None)
        return None

    def _restore_priority(self, identity: ProcessIdentity) -> Optional[str]:
        tracked = self._original_priorities.get(identity)
        if tracked is None:
            return None
        process, original_priority = tracked
        safe_process = self._get_safe_process(identity)
        if safe_process is None:
            self._original_priorities.pop(identity, None)
            return None
        try:
            safe_process.nice(original_priority)
        except psutil.NoSuchProcess:
            self._original_priorities.pop(identity, None)
            return None
        except psutil.Error as error:
            self._record_error(identity[0], error)
            return str(error)
        self._original_priorities.pop(identity, None)
        return None

    def _record_error(self, pid: object, error: psutil.Error) -> None:
        self.action_errors.append(f"PID {pid}: {type(error).__name__}: {error}")
