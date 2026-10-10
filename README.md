# FocusOS

FocusOS is a Windows desktop prototype for monitoring system resources and the
currently focused application. The desktop interface uses PySide6 Qt Quick
(QML), with Python providing the monitoring runtime and controls.

## Requirements

- Windows
- Python with `pip`

## Install and run

From the project directory, create and activate a virtual environment, install
the dependencies, and launch the application with `main.py`:

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

If PowerShell activation is unavailable, call the virtual-environment
interpreter directly:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe main.py
```

The default command opens the QML dashboard in light mode. Monitoring begins
automatically and refreshes every two seconds. The dashboard displays CPU, RAM,
disk, optional NVIDIA GPU usage, current focus, resource warnings, process
recommendations, top memory consumers, and live charts. Chart history is
limited to 120 samples. Monitoring and controls run in a worker thread so
system scans do not block the interface.

Use the dashboard buttons to start, pause, resume, stop, or emergency-disable
FocusOS. The theme toggle switches between light and dark mode for the current
session.

## `main.py` commands

Run the application and its optional tools through `main.py`:

| Command | Purpose |
| --- | --- |
| `python main.py` | Launch the Qt Quick desktop dashboard. |
| `python main.py --help` | Show all supported command-line options. |
| `python main.py --terminal` | Run the live terminal monitor instead of the dashboard. |
| `python main.py --terminal --skip-disk-review` | Run the terminal monitor without its initial disk cleanup/review. |
| `python main.py --cleanup-temp` | Clean eligible direct-child files older than one hour in the Windows temporary folder. |
| `python main.py --cleanup-folders` | Clean eligible direct-child files older than one hour in TEMP, Prefetch, and Recent. |
| `python main.py --optimize-disk` | Clean eligible old files and offer separately confirmed log, dump, and Recycle Bin cleanup. |
| `python main.py --manage-ram` | Select and explicitly confirm one eligible background process to suspend temporarily. |
| `python main.py --collect-python-garbage` | Collect unreachable Python objects in the FocusOS process only. |

Replace `python` with `.\venv\Scripts\python.exe` if the virtual environment
is not activated. Choose one maintenance option at a time.

### Terminal monitor and process controls

`--terminal` refreshes system and foreground-window information every two
seconds. By default it runs the disk cleanup/review before starting; include
`--skip-disk-review` to skip that step. It then asks which eligible background
processes, if any, may be managed for this run. Automatic suspension is only
enabled after selecting the exact process instances and typing
`AUTO SUSPEND`. Press Enter at the selection prompt to monitor without
suspending processes. Press Ctrl+C to stop and restore processes managed by
FocusOS.

The default `AUTO_SUSPEND_ALLOWLIST` in `config/settings.py` is empty.
Configuring it opts exact executable names into process controls. Suspending
an application can interrupt its work and may not immediately free its memory;
review the process before enabling controls.

### Cleanup safety

`--cleanup-temp` and `--cleanup-folders` automatically remove eligible regular
files directly inside the selected folders when they are older than one hour.
They skip nested files, locked or changed files, and reparse points. Prefetch
cleanup may make apps start more slowly while Windows rebuilds its cache;
Recent cleanup removes recently used shortcuts/history.

`--optimize-disk` also cleans eligible files in TEMP, Prefetch, and Recent.
Eligible Windows log and crash-dump files must be at least 30 days old and
require an exact confirmation. Emptying the Recycle Bin requires typing
`EMPTY RECYCLE BIN` and cannot be undone. Review each prompt before confirming.

`--manage-ram` lists eligible background processes, then requires selecting a
PID and typing `SUSPEND <PID>`. The selected process is resumed when its window
becomes foreground or when Ctrl+C stops the command. Working-set trimming may
cause an app to reload data from disk and does not guarantee a specific amount
of reclaimed memory.

## Project layout

```text
FocusOS/
|-- ai/                 # AI command and intent helpers
|-- api/                # Runtime API used within the application
|-- config/             # Runtime and cleanup settings
|-- core/               # Focus, monitoring, resource, and process managers
|-- dashboard/          # Dashboard support and legacy widget interface
|-- database/           # Database helpers
|-- ml/                 # ML mode and resource optimization helpers
|-- qml/                # Qt Quick dashboard and reusable QML components
|-- tests/              # Project smoke and behavior tests
|-- dashboard_qml.py    # Python-to-QML runtime bridge
|-- main.py             # Application and command-line entry point
|-- requirements.txt    # Python dependencies
|-- Design.md           # Prototype design specification
```

## Tests

Run the project smoke tests from the project directory:

```powershell
python -m pytest tests\test_smoke.py -q
```
