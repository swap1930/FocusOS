# FocusOS

FocusOS is a task-aware operating system prototype designed to prioritize the active application and defer background work. The project follows the architecture described in `Design.md`.

## Project structure

```text
FocusOS/
|-- core/
|   |-- focus_engine.py
|   |-- resource_manager.py
|   |-- ram_manager.py
|   |-- process_manager.py
|   |-- app_manager.py
|   |-- storage_manager.py
|-- ai/
|   |-- command_parser.py
|   |-- intent_manager.py
|   |-- llm_client.py
|-- ml/
|   |-- ml_mode.py
|   |-- resource_optimizer.py
|-- dashboard/
|   |-- main_window.py
|   |-- performance_monitor.py
|   |-- desktop_app.py
|   |-- widgets/
|-- api/
|   |-- focus_api.py
|-- database/
|   |-- database.py
|-- config/
|   |-- settings.py
|-- tests/
|-- main.py
|-- requirements.txt
|-- README.md
```

## Getting started

```bash
python -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

`main.py` is the project entry point and opens the native PySide6 desktop dashboard by default.
It starts monitoring automatically and updates existing widgets every two seconds, without
reloading a browser page:

```bash
python main.py
```

The original console workflow remains available explicitly:

```bash
.\venv\Scripts\python.exe main.py --terminal
```

The dashboard shows CPU/RAM/disk/GPU metrics, current focus, resource warnings, process priority,
and top memory consumers. It also provides Start/Pause/Resume/Stop controls and live resource and
process-count charts. Chart history is capped at 120 samples.

## Live terminal monitoring and process controls

Run the legacy terminal monitoring workflow explicitly; Uvicorn is optional and is not needed:

```bash
python main.py --terminal
```

The terminal refreshes foreground application/window/task, CPU, RAM, disk, optional
NVIDIA GPU utilization, and process counts every two seconds. GPU usage displays
as unavailable unless `nvidia-smi` is installed and can query a supported GPU.
It also shows available RAM, free disk space, and the five largest process memory
consumers in the runtime state. Suspending a process prevents it from running but
does not necessarily release its memory immediately; Windows manages reclaiming
memory, and closing an app normally is the safer way to release its resources.
The resource manager reports CPU/RAM/disk pressure (warning at 80%/85%/90%,
critical at 95%) but does not change resources without an explicitly selected
process. Focus task history is bounded to the most recent 300 snapshots to avoid
unbounded FocusOS memory growth.
The normal terminal view does not display cleanup scan results. The optional
`GET /storage/candidates` API endpoint lists old files in the system temporary
folder and common Windows cache folders as recommendations only and never
deletes files through the API.

On normal startup, FocusOS automatically removes direct-child files older than
one hour from user/system TEMP, Prefetch, and Recent. It skips files modified
within the last hour, locked, changed, nested, and reparse-point files. Old Windows logs/crash dumps and Recycle Bin
cleanup remain previewed and require explicit confirmation. Use
`--skip-disk-review` to skip the startup scan and cleanup.

To scan and automatically clean eligible old regular files directly inside the
Windows temporary folder, run:

```powershell
.\venv\Scripts\python.exe main.py --cleanup-temp
```

This command scans and automatically deletes eligible regular files directly
inside the temp folder older than one hour. It skips directories, locked,
changed, or recent files and never touches browser caches.

To clean TEMP, Prefetch, and Recent separately, run:

```powershell
.\venv\Scripts\python.exe main.py --cleanup-folders
```

FocusOS automatically removes regular files directly inside each folder when
they are older than one hour. Locked, newer, nested, changed, and reparse-point
files are skipped.
Prefetch cleanup may make apps start more slowly while Windows rebuilds its
cache; Recent cleanup removes recently-used shortcuts/history.

For a broader disk cleanup, run:

```powershell
.\venv\Scripts\python.exe main.py --optimize-disk
```

This automatically cleans eligible direct-child files older than one hour in
user/system TEMP, Prefetch, and Recent. This removes old Recent shortcuts/history
entries as well as eligible temp/cache files.
Direct `.log` files in `%SystemRoot%\Logs` and `.dmp` files in common Windows/user
crash-dump folders must be at least thirty days old and still require a separate
exact confirmation. Deletion uses an exclusive Windows file handle; locked,
recent, changed, nested, reparse-point, or out-of-scope files are skipped. The
Recycle Bin is emptied only after its size is shown and you type
`EMPTY RECYCLE BIN`; this action is not reversible.

`--collect-python-garbage` runs Python garbage collection in the FocusOS
process only. FocusOS does not flush the system-wide Windows standby list:
Windows manages standby pages and exposes no safe supported per-application
operation to empty that list. Selected-app suspension/working-set trimming is
the RAM control; it can interrupt work and does not guarantee a particular
amount of memory will be reclaimed.

Automatic process controls are opt-in. In `config/settings.py`, add exact
executable names to `AUTO_SUSPEND_ALLOWLIST`, for example:

```python
AUTO_SUSPEND_ALLOWLIST = ("notepad.exe",)
```

Only allowlisted processes owned by the current user are eligible. FocusOS
raises the active allowlisted process to high priority and restores its prior
priority when it leaves focus. It suspends allowlisted background processes
after two minutes and resumes them when that app becomes active again. The
delay is controlled by `AUTO_SUSPEND_DELAY_SECONDS`. System processes and the
FocusOS process/its parent processes are protected. Press Ctrl+C to stop and
restore processes managed by FocusOS. If FocusOS is forcibly terminated or the
computer loses power, it cannot restore a process before shutdown. Review the
allowlist carefully: suspending an application can interrupt its work.

On the same normal startup, FocusOS shows eligible background process instances
sorted by RAM use and asks which exact instances it may manage for this run. After the
explicit `AUTO SUSPEND` confirmation, only those selected instances are
automatically suspended after two minutes in the background and restored on
refocus or Ctrl+C. Press Enter or decline the confirmation to stay in monitoring
only for RAM. This approval avoids suspending an app or interrupting unsaved work
without your permission. Selecting a browser helper/renderer may interrupt a tab,
so select only processes you recognize.

For one-time, user-selected RAM management without editing the allowlist, run:

```powershell
.\venv\Scripts\python.exe main.py --manage-ram
```

FocusOS lists eligible background processes owned by the current user, sorted
by RAM use. Enter a listed PID, then type `SUSPEND <PID>` to confirm. Only that
process is suspended; it resumes when its window becomes foreground, or when
you press Ctrl+C. On Windows, FocusOS also asks Windows to trim the selected
process's resident working set and reports the measured change. This may cause
the app to reload pages from disk when resumed; Windows can reclaim less than
requested. If a process has no foreground window, use Ctrl+C to restore it and
exit. The normal monitoring command asks for explicit per-run permission before
it suspends any selected process.

The optional local API can still be run with
`uvicorn main:app --host 127.0.0.1 --port 8000`; it exposes the existing
monitoring/control routes and `GET /storage/candidates` for a fresh, read-only
cleanup scan.
