# FocusOS

FocusOS is a cross-platform desktop prototype for monitoring system resources
and the currently focused application. The desktop interface uses PySide6 Qt
Quick (QML), with Python providing the monitoring runtime and controls.

## Requirements

- Windows or Linux
- Python 3.10 or newer with `pip`

## Install and run

From the project directory, create and activate a virtual environment, install
the dependencies, and launch the application:

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

On Linux, from a graphical session:

```bash
bash scripts/run_focusos_linux.sh
```

The dashboard starts monitoring automatically, and its Start, Pause, Resume,
Stop, Emergency Disable, resource-monitoring, and ML Focus controls are retained.

## AI Terminal

The dashboard includes an AI Terminal button that opens a separate terminal
window. It provides local completions, command history, bounded output, exit
codes, and a working-directory indicator. Local suggestions are provided for
common Git, Python, and directory workflows. This is a constrained command
runner, not a full interactive system shell: only read-only Git inspection,
Python version, and directory-listing commands are supported. Python scripts,
package operations, shell interpreters, and shell syntax are blocked. Directory
navigation supports relative and absolute paths within the FocusOS project tree;
paths outside that tree are rejected. Use Up/Down to navigate suggestions (Up
at an empty selection navigates command history), Tab to fill a suggestion,
Enter to accept a highlighted suggestion or execute input, and Escape to dismiss
suggestions. Suggested commands are never executed automatically.

Optional Cohere assistance is configured using environment variables (or a
local, git-ignored `.env` file):

```text
COHERE_API_KEY=your_cohere_api_key
COHERE_MODEL=command-a-03-2025
COHERE_API_URL=https://api.cohere.com/v2/chat
```

Natural-language terminal requests require `COHERE_API_KEY` in the project-root
`.env` file. `.env.example` is only a template and is not loaded by the app. Do
not commit the key. If you receive HTTP 401, replace it with a valid key from
Cohere; revoke any key previously shared publicly. `COHERE_MODEL` and
`COHERE_API_URL` can be overridden if you use a different Cohere model or endpoint. Prompts containing the user's
request, platform, and working directory are sent to Cohere. The API key is sent
only in the authorization header and is never exposed to QML/frontend or visible
output. Model output is parsed and validated against FocusOS's restricted
command policy and requires confirmation before execution. Network requests may
take up to 30 seconds; a timeout or rejected command is reported without
executing the model's unvalidated output.

### Terminal security and limitations

This is a deliberately constrained local development terminal, not a general
shell. It invokes subprocesses using argument arrays with `shell=False`, limits
execution time and captured output, and accepts read-only Git inspection,
Python version, and directory-listing commands. Shell chaining, redirection,
privilege escalation, destructive disk/system tools, Python scripts/modules,
PowerShell/cmd/shell interpreters, package operations, and npm/Node scripts are
blocked.
The `cd` command and terminal process working directory are restricted to the
FocusOS project tree. Node/npm script execution is disabled because npm scripts
can launch arbitrary programs. FocusOS does not automatically install packages,
alter process priorities, suspend processes, or change system settings from
terminal suggestions. A general-purpose shell would require a separate sandbox
or stronger OS isolation boundary and is intentionally not implemented here.

## Existing utilities

`python main.py --help` lists the separate monitoring and maintenance CLI
options. Disk cleanup and process-management operations retain their existing
explicit safety checks; they are not exposed as terminal commands.

## Tests

Run all automated tests from the project directory:

```powershell
python -m pytest -q
```
