"""Entry point for the FocusOS prototype."""

import argparse
import gc
import os
import tempfile
import time
from pathlib import Path

from api.focus_api import FocusAPI
from config.settings import (
    CLEANUP_AUTO_MIN_AGE_SECONDS,
    CLEANUP_DIAGNOSTIC_MIN_AGE_DAYS,
    CLEANUP_MIN_AGE_DAYS,
)
from core.storage_manager import StorageManager

api = FocusAPI()
app = api.create_app()


def review_and_clean_folder(
    label: str,
    root: Path,
    confirmation_word: str,
    *,
    min_age_days: int = CLEANUP_MIN_AGE_DAYS,
    min_age_seconds=None,
    allowed_extensions=None,
    auto_delete: bool = False,
) -> None:
    """Preview and clean eligible aged direct child files in one folder."""
    manager = StorageManager(
        roots=[root],
        min_age_days=min_age_days,
        min_age_seconds=min_age_seconds,
        direct_children_only=True,
        allowed_extensions=allowed_extensions,
    )
    result = manager.scan_candidates()
    minimum_age = (
        f"{min_age_seconds / 3600:g} hours"
        if min_age_seconds is not None
        else f"{min_age_days} days"
    )
    print(
        f"\n{label}: found {result['candidate_count']} files older than "
        f"{minimum_age} directly in this folder "
        f"({result['total_bytes'] / (1024 * 1024):.1f} MB)."
    )
    if not result["candidates"]:
        print("Nothing eligible to clean.")
        return

    if not auto_delete:
        for candidate in result["candidates"]:
            print(
                f"  {candidate['size_bytes'] / (1024 * 1024):.1f} MB | "
                f"{candidate['age_days']} days old | {candidate['path']}"
            )
    if result["truncated"]:
        print("Candidate list is truncated; no files outside the list will be deleted.")
    if result["errors"]:
        for error in result["errors"][:10]:
            print(f"Scan warning: {error}")
        if len(result["errors"]) > 10:
            print(f"...and {len(result['errors']) - 10} more scan warnings.")

    if not auto_delete:
        try:
            confirmation = input(f"Type {confirmation_word} to delete only the listed files: ")
        except EOFError:
            print("No confirmation received; no files deleted.")
            return
        if confirmation != confirmation_word:
            print("Cleanup cancelled; no files deleted.")
            return

    cleanup = manager.delete_approved_candidates(result["candidates"])
    print(
        f"Removed {cleanup['removed_count']} files; "
        f"freed {cleanup['reclaimed_bytes'] / (1024 * 1024):.1f} MB."
    )
    for error in cleanup["errors"]:
        print(f"Skipped: {error}")


def cleanup_temp_files() -> None:
    """Automatically clean eligible old direct files in the temp folder."""
    review_and_clean_folder(
        "TEMP",
        Path(tempfile.gettempdir()),
        "DELETE TEMP",
        min_age_seconds=CLEANUP_AUTO_MIN_AGE_SECONDS,
        auto_delete=True,
    )


def cleanup_system_folders() -> None:
    """Automatically clean eligible old files from TEMP, Prefetch, and Recent."""
    windows_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    app_data = os.environ.get("APPDATA")
    folders = [
        ("TEMP", Path(tempfile.gettempdir()), "DELETE TEMP"),
        ("PREFETCH", windows_root / "Prefetch", "DELETE PREFETCH"),
    ]
    if app_data:
        folders.append(
            (
                "RECENT",
                Path(app_data) / "Microsoft" / "Windows" / "Recent",
                "DELETE RECENT",
            )
        )

    for label, folder, confirmation in folders:
        if folder.is_dir():
            review_and_clean_folder(
                label,
                folder,
                confirmation,
                min_age_seconds=CLEANUP_AUTO_MIN_AGE_SECONDS,
                auto_delete=True,
            )
        else:
            print(f"\n{label}: folder not found; skipped.")


def optimize_disk() -> None:
    """Clean eligible cache files and review higher-risk log/dump cleanup."""
    windows_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    local_app_data = os.environ.get("LOCALAPPDATA")
    targets = [
        ("USER TEMP", Path(tempfile.gettempdir()), "DELETE USER TEMP", CLEANUP_MIN_AGE_DAYS, None, True),
        ("SYSTEM TEMP", windows_root / "Temp", "DELETE SYSTEM TEMP", CLEANUP_MIN_AGE_DAYS, None, True),
        ("PREFETCH", windows_root / "Prefetch", "DELETE PREFETCH", CLEANUP_MIN_AGE_DAYS, None, True),
        (
            "WINDOWS LOG FILES",
            windows_root / "Logs",
            "DELETE OLD LOGS",
            CLEANUP_DIAGNOSTIC_MIN_AGE_DAYS,
            {".log"},
            False,
        ),
        (
            "WINDOWS MINIDUMPS",
            windows_root / "Minidump",
            "DELETE OLD DUMPS",
            CLEANUP_DIAGNOSTIC_MIN_AGE_DAYS,
            {".dmp", ".mdmp", ".hdmp"},
            False,
        ),
        (
            "LIVE KERNEL DUMPS",
            windows_root / "LiveKernelReports",
            "DELETE OLD DUMPS",
            CLEANUP_DIAGNOSTIC_MIN_AGE_DAYS,
            {".dmp", ".mdmp", ".hdmp"},
            False,
        ),
    ]
    app_data = os.environ.get("APPDATA")
    if app_data:
        targets.append(
            (
                "RECENT",
                Path(app_data) / "Microsoft" / "Windows" / "Recent",
                "DELETE RECENT",
                CLEANUP_MIN_AGE_DAYS,
                None,
                True,
            )
        )
    if local_app_data:
        targets.append(
            (
                "USER CRASH DUMPS",
                Path(local_app_data) / "CrashDumps",
                "DELETE OLD DUMPS",
                CLEANUP_DIAGNOSTIC_MIN_AGE_DAYS,
                {".dmp", ".mdmp", ".hdmp"},
                False,
            )
        )

    print(
        "Old files in TEMP, Prefetch, and Recent are cleaned automatically. "
        "Logs, dumps, and Recycle Bin require explicit confirmation."
    )
    seen_roots = set()
    for label, root, confirmation, min_age_days, extensions, auto_delete in targets:
        normalized_root = os.path.normcase(os.path.abspath(root))
        if normalized_root in seen_roots:
            continue
        seen_roots.add(normalized_root)
        if root.is_dir():
            review_and_clean_folder(
                label,
                root,
                confirmation,
                min_age_days=min_age_days,
                min_age_seconds=(
                    CLEANUP_AUTO_MIN_AGE_SECONDS if auto_delete else None
                ),
                allowed_extensions=extensions,
                auto_delete=auto_delete,
            )
        else:
            print(f"\n{label}: folder not found or inaccessible; skipped.")

    try:
        recycle_bin = StorageManager.recycle_bin_usage()
    except OSError as error:
        print(f"\nRecycle Bin could not be inspected: {error}")
        return

    print(
        f"\nRECYCLE BIN: {recycle_bin['items']} items, "
        f"{recycle_bin['bytes'] / (1024 * 1024):.1f} MB."
    )
    if recycle_bin["items"] == 0:
        return
    try:
        confirmation = input("Type EMPTY RECYCLE BIN to empty it: ")
    except EOFError:
        print("No confirmation received; Recycle Bin unchanged.")
        return
    if confirmation != "EMPTY RECYCLE BIN":
        print("Recycle Bin cleanup cancelled.")
        return
    try:
        StorageManager.empty_recycle_bin()
    except OSError as error:
        print(f"Recycle Bin cleanup failed: {error}")
        return
    print("Recycle Bin emptied.")


def configure_auto_ram_management(state: dict) -> None:
    """Ask which exact background process instances may be suspended automatically."""
    manager = api.runtime.process_manager
    try:
        active_pid = api.runtime.monitor.get_active_window_pid()
    except (OSError, RuntimeError) as error:
        print(f"Foreground app could not be verified; automatic suspension disabled: {error}")
        return

    candidates = manager.list_suspend_candidates(state["priority_plan"] or [], active_pid)
    if not candidates:
        print("No eligible background processes found; automatic suspension disabled.")
        return

    print(
        "\nSelect background process instances for automatic suspension. "
        "System/protected and foreground processes are excluded."
    )
    for index, candidate in enumerate(candidates[:20], start=1):
        print(
            f"  {index}. PID {candidate['pid']} | {candidate['memory_mb']:.0f} MB | "
            f"{candidate['name']}"
        )
    if len(candidates) > 20:
        print("  Only the 20 largest eligible processes are listed.")

    try:
        selection = input(
            "Enter selection numbers separated by commas, or press Enter for monitoring only: "
        ).strip()
    except EOFError:
        print("No selection received; automatic suspension disabled.")
        return
    if not selection:
        return

    try:
        indexes = {int(part.strip()) for part in selection.split(",")}
    except ValueError:
        print("Invalid selection; automatic suspension disabled.")
        return
    if not indexes or any(index < 1 or index > min(len(candidates), 20) for index in indexes):
        print("Selection is outside the listed range; automatic suspension disabled.")
        return

    selected = [candidates[index - 1] for index in sorted(indexes)]
    print("Selected for possible suspension after two minutes in the background:")
    for candidate in selected:
        print(f"  PID {candidate['pid']} | {candidate['name']} | {candidate['memory_mb']:.0f} MB")
    try:
        confirmation = input("Type AUTO SUSPEND to enable this for this run: ")
    except EOFError:
        print("No confirmation received; automatic suspension disabled.")
        return
    if confirmation != "AUTO SUSPEND":
        print("Automatic suspension cancelled; monitoring only.")
        return

    manager.selected_instances.update(
        (int(candidate["pid"]), float(candidate["create_time"]))
        for candidate in selected
    )


def manage_ram() -> None:
    """Let the user select one background process to temporarily suspend."""
    try:
        state = api.runtime.start()
        manager = api.runtime.process_manager
        active_pid = api.runtime.monitor.get_active_window_pid()
        candidates = manager.list_suspend_candidates(state["priority_plan"] or [], active_pid)
        if not candidates:
            print("No eligible background app processes found to suspend.")
            return

        print(
            "Choose only an app process you recognize. Suspending can pause its work "
            "and may not immediately free RAM."
        )
        for candidate in candidates[:20]:
            print(
                f"PID {candidate['pid']} | {candidate['memory_mb']:.0f} MB | "
                f"{candidate['name']}"
            )
        try:
            selected_pid = int(input("Enter one PID to inspect, or press Enter to cancel: "))
        except EOFError:
            print("No selection received; no process was suspended.")
            return
        except ValueError:
            print("Invalid PID; no process was suspended.")
            return
        candidate = next(
            (item for item in candidates if item["pid"] == selected_pid),
            None,
        )
        if candidate is None:
            print("PID was not in the eligible list; no process was suspended.")
            return
        try:
            confirmation = input(
                f"Type SUSPEND {selected_pid} to temporarily suspend "
                f"{candidate['name']}: "
            )
        except EOFError:
            print("No confirmation received; process was not suspended.")
            return
        if confirmation != f"SUSPEND {selected_pid}":
            print("Suspension cancelled.")
            return

        trimmed_bytes, trim_warning = manager.suspend_selected_process(
            selected_pid,
            float(candidate["create_time"]),
            str(candidate["name"]),
        )
        print(
            f"Suspended {candidate['name']} (PID {selected_pid}); "
            f"working set reduced by about {trimmed_bytes / (1024 * 1024):.1f} MB. "
            "It will resume when its window becomes foreground; Ctrl+C also restores it."
        )
        if trim_warning:
            print(f"RAM warning: {trim_warning}")
        while manager.selected_process_is_running(
            selected_pid,
            float(candidate["create_time"]),
        ):
            if api.runtime.monitor.get_active_window_pid() == selected_pid:
                error = manager.resume_selected_process(
                    selected_pid,
                    float(candidate["create_time"]),
                )
                if error:
                    print(f"Resume warning: {error}")
                else:
                    print(f"\nResumed {candidate['name']} (PID {selected_pid}).")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nRestoring selected process...")
    except RuntimeError as error:
        print(f"Process control refused: {error}")
    finally:
        stopped_state = api.runtime.stop()
        for error in stopped_state["process_action_errors"]:
            print(f"Restore warning: {error}")


def main():
    """Run cleanup on explicit request, otherwise monitor the system."""
    parser = argparse.ArgumentParser(
        description="FocusOS monitoring with user-approved process and file controls."
    )
    parser.add_argument(
        "--cleanup-temp",
        action="store_true",
        help="scan and automatically delete eligible old files directly in the temp folder",
    )
    parser.add_argument(
        "--cleanup-folders",
        action="store_true",
        help="scan and automatically clean eligible old files in temp, Prefetch, and Recent",
    )
    parser.add_argument(
        "--manage-ram",
        action="store_true",
        help="choose one verified background app process to suspend temporarily",
    )
    parser.add_argument(
        "--optimize-disk",
        action="store_true",
        help="automatically clean old temp/cache files; confirm log/dump and Recycle Bin cleanup",
    )
    parser.add_argument(
        "--collect-python-garbage",
        action="store_true",
        help="collect unreachable Python objects in FocusOS only",
    )
    parser.add_argument(
        "--skip-disk-review",
        action="store_true",
        help="start monitoring without reviewing disk-cleanup candidates",
    )
    args = parser.parse_args()
    if args.cleanup_temp:
        cleanup_temp_files()
        return
    if args.cleanup_folders:
        cleanup_system_folders()
        return
    if args.manage_ram:
        manage_ram()
        return
    if args.optimize_disk:
        optimize_disk()
        return
    if args.collect_python_garbage:
        print(f"Collected {gc.collect()} unreachable FocusOS Python objects.")
        return

    if not args.skip_disk_review:
        optimize_disk()

    api.runtime.start()
    configure_auto_ram_management(api.runtime.snapshot())
    allowlist = sorted(api.runtime.process_manager.allowlist)
    selected_count = api.runtime.process_manager.selected_process_count
    if selected_count:
        print(
            f"\nAutomatic suspension enabled for {selected_count} selected process "
            "instance(s) after two minutes in the background."
        )
    elif allowlist:
        print(
            "\nAutomatic process controls enabled for: "
            + ", ".join(allowlist)
            + ". Background apps are suspended after two minutes."
        )
    else:
        print(
            "\nNo process allowlist configured; FocusOS will monitor and recommend "
            "without changing processes."
        )
    print("Press Ctrl+C to restore FocusOS-managed processes and stop.\n")

    previous_resource_warnings = None
    try:
        while True:
            state = api.get_state()
            ram_available_gb = state["ram_available_bytes"] / (1024 ** 3)
            disk_free_gb = state["disk_free_bytes"] / (1024 ** 3)
            top_memory = state["top_memory_processes"][0] if state["top_memory_processes"] else None
            top_memory_display = (
                f"{top_memory['name']} {top_memory['memory_mb']:.0f}MB"
                if top_memory
                else "N/A"
            )
            print(
                f"\r{state['status']} | "
                f"App: {state['focus_application'] or 'Unknown'} | "
                f"Window: {state['focus_window'] or 'Unknown'} | "
                f"Mode: {state['focus_mode']} | "
                f"Focus: {state['focus_score']}% | "
                f"CPU: {state['cpu_usage']}% | "
                f"RAM: {state['ram_usage']}% ({ram_available_gb:.1f}GB free) | "
                f"Disk: {state['disk_usage']}% ({disk_free_gb:.2f}GB free) | "
                f"Resources: {state['resource_status']} | "
                f"Largest RAM process: {top_memory_display} | "
                f"GPU: {state['gpu_usage'] if state['gpu_usage'] is not None else 'N/A'} | "
                f"Processes: {state['active_processes']} active, "
                f"{state['background_processes']} background, "
                f"{state['suspended_processes']} suspended | "
                f"Working set trimmed: "
                f"{state['working_set_trimmed_bytes'] / (1024 * 1024):.1f} MB",
                end="",
                flush=True,
            )
            resource_warnings = tuple(state["resource_warnings"])
            if resource_warnings != previous_resource_warnings:
                if resource_warnings:
                    print("\n" + " ".join(resource_warnings), flush=True)
                elif previous_resource_warnings:
                    print("\nResource pressure cleared.", flush=True)
                previous_resource_warnings = resource_warnings
            if state["process_action_errors"]:
                print(
                    "\nProcess control warning: "
                    + "; ".join(state["process_action_errors"]),
                    flush=True,
                )
            time.sleep(2)
    except KeyboardInterrupt:
        print("\nStopping FocusOS monitoring...")
    finally:
        stopped_state = api.runtime.stop()
        for error in stopped_state["process_action_errors"]:
            print(f"Restore warning: {error}")
        print("FocusOS monitoring stopped.")


if __name__ == "__main__":
    main()
