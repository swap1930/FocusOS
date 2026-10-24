"""Smart storage cleanup and safe file recommendations."""

from __future__ import annotations

import os
import stat
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set

from config.settings import CLEANUP_MAX_CANDIDATES, CLEANUP_MIN_AGE_DAYS


class StorageManager:
    """Find old cache/temp files and safely delete eligible candidates."""

    def __init__(
        self,
        roots: Optional[Iterable[Path]] = None,
        min_age_days: int = CLEANUP_MIN_AGE_DAYS,
        max_candidates: int = CLEANUP_MAX_CANDIDATES,
        clock: float = time.time,
        direct_children_only: bool = False,
        allowed_extensions: Optional[Iterable[str]] = None,
        file_deleter: Optional[Callable[[Path], None]] = None,
        min_age_seconds: Optional[float] = None,
    ):
        self.safe_cleanup_targets = []
        self.roots = list(roots) if roots is not None else self._default_roots()
        self.min_age_seconds = (
            min_age_seconds
            if min_age_seconds is not None
            else min_age_days * 24 * 60 * 60
        )
        self.max_candidates = max_candidates
        self._clock = clock
        self.direct_children_only = direct_children_only
        self.allowed_extensions: Optional[Set[str]] = (
            {extension.casefold() for extension in allowed_extensions}
            if allowed_extensions is not None
            else None
        )
        self._file_deleter = file_deleter or self._delete_unlocked_file

    def add_candidate(self, path: str):
        """Add a candidate to the cleanup queue."""
        self.safe_cleanup_targets.append(path)
        return self.safe_cleanup_targets

    @staticmethod
    def get_safe_system_roots() -> List[Path]:
        """Collect existing safe cleanup target directories on the host."""
        roots = [Path(tempfile.gettempdir())]
        local_app_data = os.environ.get("LOCALAPPDATA")
        app_data = os.environ.get("APPDATA")
        system_root = os.environ.get("SystemRoot", r"C:\Windows")

        if os.name != "nt":
            cache_home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
            roots.extend(
                [
                    cache_home / "thumbnails",
                    cache_home / "mozilla" / "firefox" / "Profiles",
                    cache_home / "google-chrome" / "Default" / "Cache",
                    cache_home / "chromium" / "Default" / "Cache",
                ]
            )

        if local_app_data:
            local = Path(local_app_data)
            roots.extend(
                [
                    local / "Microsoft" / "Windows" / "INetCache",
                    local / "Google" / "Chrome" / "User Data" / "Default" / "Cache",
                    local / "Microsoft" / "Edge" / "User Data" / "Default" / "Cache",
                    local / "BraveSoftware" / "Brave-Browser" / "User Data" / "Default" / "Cache",
                    local / "Packages",
                ]
            )
        if app_data:
            roots.append(Path(app_data) / "Microsoft" / "Windows" / "Recent")
        if system_root and os.name == "nt":
            sys_path = Path(system_root)
            roots.extend(
                [
                    sys_path / "Temp",
                    sys_path / "Prefetch",
                ]
            )
        return [r for r in roots if r.is_dir()]

    @staticmethod
    def _default_roots() -> List[Path]:
        return StorageManager.get_safe_system_roots()

    def clean_all_safe_caches(
        self,
        min_age_seconds: Optional[float] = None,
    ) -> Dict[str, object]:
        """Automatically remove old eligible files from configured cache/temp roots."""
        original_min_age = self.min_age_seconds
        if min_age_seconds is not None:
            self.min_age_seconds = min_age_seconds
        try:
            scan = self.scan_candidates()
            candidates = scan.get("candidates") or []
            if not candidates:
                return {
                    "candidate_count": 0,
                    "removed_count": 0,
                    "reclaimed_bytes": 0,
                    "reclaimed_mb": 0.0,
                    "removed": [],
                    "errors": scan.get("errors") or [],
                }
            cleanup = self.delete_approved_candidates(candidates)
            reclaimed_bytes = int(cleanup.get("reclaimed_bytes", 0))
            return {
                "candidate_count": len(candidates),
                "removed_count": int(cleanup.get("removed_count", 0)),
                "reclaimed_bytes": reclaimed_bytes,
                "reclaimed_mb": round(reclaimed_bytes / (1024 * 1024), 2),
                "removed": cleanup.get("removed") or [],
                "errors": [*(scan.get("errors") or []), *(cleanup.get("errors") or [])],
            }
        finally:
            self.min_age_seconds = original_min_age

    def scan_candidates(self) -> Dict[str, object]:
        """List old temporary/cache files as recommendations; never remove them."""
        now = self._clock()
        cutoff = now - self.min_age_seconds
        candidates: List[Dict[str, object]] = []
        errors: List[str] = []
        candidate_count = 0
        total_bytes = 0
        seen_roots = set()
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

        def on_walk_error(error: OSError) -> None:
            errors.append(f"{error.filename or 'directory'}: {error}")

        def is_reparse_point(path: str) -> bool:
            try:
                metadata = os.lstat(path)
            except (FileNotFoundError, PermissionError) as error:
                errors.append(f"{path}: {error}")
                return True
            return os.path.islink(path) or bool(
                getattr(metadata, "st_file_attributes", 0) & reparse_flag
            )

        for configured_root in self.roots:
            root = Path(configured_root)
            normalized_root = os.path.normcase(os.path.abspath(root))
            if normalized_root in seen_roots:
                continue
            seen_roots.add(normalized_root)
            if not root.exists() or is_reparse_point(str(root)) or not root.is_dir():
                continue

            for directory, child_directories, filenames in os.walk(
                root, topdown=True, followlinks=False, onerror=on_walk_error
            ):
                child_directories[:] = [
                    name for name in child_directories
                    if not is_reparse_point(os.path.join(directory, name))
                ]
                if self.direct_children_only and Path(directory) == root:
                    child_directories.clear()
                for filename in filenames:
                    path = os.path.join(directory, filename)
                    try:
                        metadata = os.stat(path, follow_symlinks=False)
                    except (FileNotFoundError, PermissionError) as error:
                        errors.append(f"{path}: {error}")
                        continue

                    if (
                        stat.S_ISLNK(metadata.st_mode)
                        or getattr(metadata, "st_file_attributes", 0) & reparse_flag
                        or not stat.S_ISREG(metadata.st_mode)
                        or metadata.st_mtime > cutoff
                        or (
                            self.allowed_extensions is not None
                            and Path(filename).suffix.casefold() not in self.allowed_extensions
                        )
                    ):
                        continue

                    candidate_count += 1
                    total_bytes += metadata.st_size
                    if len(candidates) < self.max_candidates:
                        candidates.append(
                            {
                                "path": path,
                                "size_bytes": metadata.st_size,
                                "modified_time": metadata.st_mtime,
                                "device": metadata.st_dev,
                                "inode": metadata.st_ino,
                                "age_days": round((now - metadata.st_mtime) / 86400, 1),
                            }
                        )

        candidates.sort(key=lambda item: int(item["size_bytes"]), reverse=True)
        self.safe_cleanup_targets = [str(item["path"]) for item in candidates]
        return {
            "candidate_count": candidate_count,
            "total_bytes": total_bytes,
            "candidates": candidates,
            "truncated": candidate_count > len(candidates),
            "errors": errors,
        }

    def delete_approved_candidates(
        self,
        candidates: List[Dict[str, object]],
    ) -> Dict[str, object]:
        """Delete old regular files directly inside configured safe roots."""
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        safe_roots = []
        for configured_root in self.roots:
            root = Path(os.path.abspath(configured_root))
            try:
                root_metadata = os.lstat(root)
            except OSError:
                continue
            if (
                stat.S_ISDIR(root_metadata.st_mode)
                and not getattr(root_metadata, "st_file_attributes", 0) & reparse_flag
            ):
                safe_roots.append(root)

        cutoff = self._clock() - self.min_age_seconds
        removed: List[str] = []
        errors: List[str] = []
        reclaimed_bytes = 0
        for candidate in candidates:
            candidate_path = Path(str(candidate.get("path", "")))
            parent = os.path.normcase(os.path.abspath(candidate_path.parent))
            if not any(parent == os.path.normcase(os.path.abspath(root)) for root in safe_roots):
                errors.append(f"Skipped outside configured cleanup roots: {candidate_path}")
                continue

            try:
                metadata = os.lstat(candidate_path)
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or getattr(metadata, "st_file_attributes", 0) & reparse_flag
                    or metadata.st_mtime > cutoff
                    or metadata.st_size != candidate.get("size_bytes")
                    or metadata.st_mtime != candidate.get("modified_time")
                    or metadata.st_dev != candidate.get("device")
                    or metadata.st_ino != candidate.get("inode")
                    or (
                        self.allowed_extensions is not None
                        and candidate_path.suffix.casefold() not in self.allowed_extensions
                    )
                ):
                    errors.append(f"Skipped changed, recent, or non-regular file: {candidate_path}")
                    continue
                self._file_deleter(candidate_path)
            except OSError as error:
                errors.append(f"{candidate_path}: {error}")
                continue

            removed.append(str(candidate_path))
            reclaimed_bytes += metadata.st_size

        return {
            "removed_count": len(removed),
            "reclaimed_bytes": reclaimed_bytes,
            "removed": removed,
            "errors": errors,
        }

    @staticmethod
    def _delete_unlocked_file(path: Path) -> None:
        """Delete a validated regular file using the host platform's file API."""
        if os.name != "nt":
            path.unlink()
            return

        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class FileAttributeTagInfo(ctypes.Structure):
            _fields_ = [("attributes", wintypes.DWORD), ("reparse_tag", wintypes.DWORD)]

        create_file = kernel32.CreateFileW
        create_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create_file.restype = wintypes.HANDLE
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        get_file_info = kernel32.GetFileInformationByHandleEx
        get_file_info.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        get_file_info.restype = wintypes.BOOL
        set_file_info = kernel32.SetFileInformationByHandle
        set_file_info.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        set_file_info.restype = wintypes.BOOL

        handle = create_file(
            str(path),
            0x00010000 | 0x00000080,
            0,
            None,
            3,
            0x00200000,
            None,
        )
        invalid_handle = wintypes.HANDLE(-1).value
        if handle == invalid_handle:
            raise ctypes.WinError(ctypes.get_last_error())

        try:
            attributes = FileAttributeTagInfo()
            if not get_file_info(handle, 9, ctypes.byref(attributes), ctypes.sizeof(attributes)):
                raise ctypes.WinError(ctypes.get_last_error())
            if attributes.attributes & (0x00000010 | 0x00000400):
                raise OSError(f"Refusing to delete directory or reparse point: {path}")

            delete_info = ctypes.c_ubyte(True)
            if not set_file_info(handle, 4, ctypes.byref(delete_info), ctypes.sizeof(delete_info)):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            close_handle(handle)

    @staticmethod
    def recycle_bin_usage() -> Dict[str, int]:
        """Return the current Windows Recycle Bin item count and byte size."""
        if os.name != "nt":
            raise OSError("Recycle Bin inspection is supported on Windows only.")

        import ctypes

        class RecycleBinInfo(ctypes.Structure):
            _fields_ = [
                ("size_of_struct", ctypes.c_uint32),
                ("size", ctypes.c_longlong),
                ("items", ctypes.c_longlong),
            ]

        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        query = shell32.SHQueryRecycleBinW
        query.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(RecycleBinInfo)]
        query.restype = ctypes.c_long
        info = RecycleBinInfo()
        info.size_of_struct = ctypes.sizeof(RecycleBinInfo)
        result = query(None, ctypes.byref(info))
        if result < 0:
            raise OSError(f"Recycle Bin query failed (HRESULT 0x{result & 0xFFFFFFFF:08X}).")
        return {"items": int(info.items), "bytes": int(info.size)}

    @staticmethod
    def empty_recycle_bin() -> None:
        """Empty the user's Windows Recycle Bin without UI after explicit approval."""
        if os.name != "nt":
            raise OSError("Recycle Bin cleanup is supported on Windows only.")

        import ctypes

        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        empty = shell32.SHEmptyRecycleBinW
        empty.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong]
        empty.restype = ctypes.c_long
        no_confirmation_progress_or_sound = 0x00000001 | 0x00000002 | 0x00000004
        result = empty(None, None, no_confirmation_progress_or_sound)
        if result < 0:
            raise OSError(f"Recycle Bin cleanup failed (HRESULT 0x{result & 0xFFFFFFFF:08X}).")
