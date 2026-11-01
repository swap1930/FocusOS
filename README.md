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
window backed by a real PTY shell session. It provides local completions, command
history, bounded displayed output, and a working-directory indicator. Cohere can
generate general-purpose Windows PowerShell/CMD, Linux, or macOS shell commands,
including file operations, package installation, scripts, Git, build tools, and
multi-step workflows. Once the API returns a valid workflow, it is sent directly
to the existing PTY and its output appears in the terminal. The prompt input is
disabled while the workflow is being generated or running. AI-generated commands
can make changes using the current user's operating-system permissions; review
requests carefully. Use Up/Down to navigate suggestions (Up at an empty selection
navigates command history), Tab to fill a suggestion, Enter to accept a
highlighted suggestion or execute input, and Escape to dismiss suggestions.

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
`COHERE_API_URL` can be overridden if you use a different Cohere model or
endpoint. Prompts containing the user's request, platform, and working
directory are sent to Cohere. The API key is sent
only in the authorization header and is never exposed to QML/frontend or visible
output. Model output is parsed and checked for valid bounded command text, then
sent automatically to the real PTY. It is not treated as trusted; review natural-
language requests carefully because generated commands can modify or delete data.
Network requests may take up to 30 seconds; a timeout or invalid response is
reported without executing model output.

### Terminal security and limitations

The AI terminal is a general-purpose local shell. Valid AI-generated workflows
are automatically sent to the existing PTY as soon as the API response is
validated; they are not treated as trusted. The prompt input is locked while a
request or command is in progress. The shell inherits the current user's
operating-system permissions, so generated commands can modify or delete data.
Review natural-language requests carefully; this flow is not a substitute for
OS-level sandboxing or backups. PTY output is bounded in the UI, and process/session
cleanup remains handled by the terminal service.

## Existing utilities

`python main.py --help` lists the separate monitoring and maintenance CLI
options. Disk cleanup and process-management operations retain their existing
explicit safety checks; they are not exposed as terminal commands.

## Tests

Run all automated tests from the project directory:

```powershell
python -m pytest -q
```
