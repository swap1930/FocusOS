# FocusOS

FocusOS is a cross-platform desktop prototype for monitoring system resources
and the currently focused application. The desktop interface uses PySide6 Qt
Quick (QML), with Python providing the monitoring runtime and controls.

## Requirements

- Windows or Linux
- Python 3.10 or newer with `pip`

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

### Linux

From a graphical Linux session, run the setup/launcher script:

```bash
bash scripts/run_focusos_linux.sh
```

It creates `.venv`, installs the Python requirements, and launches the
dashboard. On X11, install `xdotool` for active-window detection (for example,
`sudo apt install xdotool` on Ubuntu/Debian). On GNOME Wayland, FocusOS
automatically installs and enables its active-window extension in the current
user's GNOME extensions folder without root access. The extension reports the
focused window's PID, application class, and title over the local user D-Bus
session. Other Wayland desktops still need their own compositor-specific
integration.

On Linux, FocusOS detects the platform automatically, monitors resources, and
uses reversible `SCHED_BATCH` scheduling for eligible current-user background
processes; the original scheduling policy is restored when an app regains
focus or monitoring pauses/stops. The selected profile sets the delay before it requests
`process_madvise(MADV_PAGEOUT)` for up to 64 MiB of private mappings per
process. This requires kernel pidfd/process-madvise support and ptrace access,
so the kernel may deny the request; FocusOS reports the result rather than
claiming RAM was freed. Protected system/desktop processes, other users'
processes, FocusOS and its parent processes are excluded. X11 focus detection
needs `xdotool`; GNOME Wayland uses the user extension described above. Other
Wayland desktops report focus as unavailable, so automatic process controls
remain inactive there. Explicitly allowlisted process suspend/resume is also
supported. Windows-only disk cleanup commands remain Windows-only.

Build a separate Linux executable with:

```bash
bash scripts/build_focusos_linux.sh
```

This produces a Linux binary under `dist/FocusOS`; a Windows `.exe` cannot run
on Linux, so build a separate executable on each operating system.

The default command opens the QML dashboard in light mode. Monitoring begins
automatically and refreshes every two seconds. The dashboard displays CPU, RAM,
disk, optional NVIDIA GPU usage, current focus, resource warnings, process
recommendations, top memory consumers, and live charts. Chart history is
limited to 120 samples. Monitoring and controls run in a worker thread so
system scans do not block the interface.

Use the dashboard buttons to start, pause, resume, stop, or emergency-disable
FocusOS. The theme toggle switches between light and dark mode for the current
session.

FocusOS automatically tunes resource policies based on the active tab and
application window:
- **Focus**: automatically activates during coding, meetings, AI/ML study, or
  focused work (e.g., VS Code, GitHub, LeetCode, Stack Overflow, Colab, Google
  Meet). It requests background memory cleanup after 1 minute and uses tighter
  warning thresholds (CPU 70%, RAM 75%, disk 90%).
- **Balanced**: automatically activates for general web browsing and casual tasks
  (e.g., YouTube, Reddit, social media, idle browsing). It applies background
  memory cleanup after 2 minutes with standard thresholds (CPU 80%, RAM 85%, disk 90%).
- **Performance**: automatically activates for heavy creative workloads and rendering
  (e.g., Figma, Canva, Blender, 3D rendering). It uses a relaxed 5-minute cleanup
  delay and higher warning thresholds (CPU 90%, RAM 90%, disk 95%).

While monitoring is running, automatic optimization raises the verified
foreground app to Windows' above-normal priority and lowers eligible
current-user background apps to below-normal priority. Once the delay configured
by the active profile expires, FocusOS asks Windows to trim each eligible app's
working set once.
This can evict resident pages but does not transfer or guarantee RAM; Windows
or the app may load those pages again. System/protected processes, processes
owned by another user, FocusOS, and its parent processes are excluded. Pausing
or stopping restores process priorities and resumes any explicitly allowlisted
processes FocusOS suspended. If Windows denies changes to eligible apps, use
the dashboard's **Restart as administrator** button and approve the UAC prompt.
The elevated dashboard starts only after the current instance has shut down;
Windows may still deny access to protected processes.

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
