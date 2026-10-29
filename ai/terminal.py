"""Safe local pseudo-terminal and AI terminal services for FocusOS.

Provides genuine interactive shell sessions (using PTY on Windows and Unix),
native working directory selection, real-time autocomplete suggestions,
and Hugging Face-powered natural-language command generation with multi-step
previews, confirmation, editing, and safety validation.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import winpty
    from winpty.enums import Backend as WinptyBackend
    _WINPTY_AVAILABLE = True
except (ImportError, Exception):
    _WINPTY_AVAILABLE = False
    WinptyBackend = None  # type: ignore[assignment]


MAX_COMMAND_LENGTH = 1024
MAX_OUTPUT_CHARS = 100_000
MAX_HISTORY = 200
DEFAULT_TIMEOUT_SECONDS = 15
AI_TIMEOUT_SECONDS = 5

LOCAL_COMMANDS = (
    ("git status", "Show the working tree status"),
    ("git diff", "Show unstaged changes"),
    ("git log", "Show recent commits"),
    ("git branch", "List branches"),
    ("git pull", "Fetch and integrate with remote branch"),
    ("git add .", "Stage all changes"),
    ("python --version", "Show the Python version"),
    ("python -m venv .venv", "Create a project virtual environment"),
    ("python -m pytest", "Run project tests"),
    ("pip install -r requirements.txt", "Install project dependencies"),
    ("pip list", "List installed packages"),
    ("pytest -v", "Run pytest with verbose output"),
    ("pwd", "Show the current directory"),
    ("ls -la", "List files and directories with details"),
    ("dir", "List files and directories"),
    ("npm install", "Install npm packages"),
    ("npm test", "Run package tests"),
    ("npm run dev", "Run npm dev script"),
    ("cls", "Clear the terminal screen"),
    ("clear", "Clear the terminal screen"),
    ("echo", "Print text to standard output"),
)

_ALLOWED_ROOTS = {
    "git", "python", "python3", "py", "pip", "pip3", "npm", "node", "pwd", "ls", "dir", "cd",
    "pytest", "echo", "cls", "clear", "type", "cat", "whoami", "hostname", "set", "env",
}

_BLOCKED_PATTERNS = re.compile(
    r"(^|\s)(?:rm|rmdir|del|erase|format|diskpart|shutdown|reboot|mkfs|dd|sudo|su|runas|powershell|pwsh|cmd|bash|sh|taskkill|reg|sc)\b|[;&|<>`]",
    re.IGNORECASE,
)

DESTRUCTIVE_PATTERN = re.compile(
    r"(?:^|\s|[;&|])(?:rm\s+-[a-zA-Z]*[rf]|rmdir\s+/[sS]|rd\s+/[sS]|del\s+/[sSfFqQ]|erase\s+/[sS]|"
    r"format\s+[a-zA-Z]:|diskpart\b|mkfs\b|dd\s+if=|git\s+reset\s+--hard|git\s+clean\s+-[a-zA-Z]*f|"
    r"git\s+push\s+--force|drop\s+database|drop\s+table|truncate\s+table|shutdown\b|reboot\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Suggestion:
    command: str
    explanation: str
    source: str = "local"


def strip_ansi(text: str) -> str:
    """Strip ANSI control sequences and normalize newlines for UI rendering."""
    if not text:
        return ""
    text = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", text)
    text = re.sub(r"\x1b\([a-zA-Z]", "", text)
    text = re.sub(r"\x1b\][0-9;]*\x07", "", text)
    text = text.replace("\r\r\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    return text


def is_destructive_command(command: str) -> bool:
    """Return True if the command contains potentially destructive operations."""
    if not isinstance(command, str) or not command.strip():
        return False
    return bool(DESTRUCTIVE_PATTERN.search(command))


def filesystem_path(value: str | os.PathLike[str]) -> Path:
    """Convert a local file URL or filesystem path to a decoded Path."""
    raw = os.fspath(value)
    if raw.casefold().startswith("file:"):
        parsed = urlparse(raw)
        path = unquote(parsed.path)
        if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]
        if parsed.netloc and parsed.netloc.casefold() != "localhost":
            path = f"//{parsed.netloc}{path}"
        return Path(path)
    return Path(raw).expanduser()


def _safe_cwd(candidate: str | os.PathLike[str] | None = None) -> Path:
    """Return an existing accessible directory, falling back to the project root."""
    root = Path(__file__).resolve().parent.parent
    if candidate is None:
        return root
    try:
        selected = filesystem_path(candidate).expanduser().resolve(strict=True)
        if selected.is_dir() and os.access(selected, os.R_OK | os.X_OK):
            return selected
    except (OSError, RuntimeError, ValueError):
        pass
    return root


def _directory_suggestions(partial: str, cwd: Path) -> list[Suggestion]:
    raw = partial.strip()
    if raw != "cd" and (not raw.startswith("cd ") and not raw.startswith("cd\t")):
        return []
    prefix = raw[2:].strip().strip('"').strip("'").casefold()
    try:
        entries = sorted(cwd.iterdir(), key=lambda item: item.name.casefold())[:200]
        results = []
        for entry in entries:
            if not entry.is_dir() or entry.is_symlink():
                continue
            name = entry.name
            if prefix and not name.casefold().startswith(prefix):
                continue
            formatted = f'cd "{name}"' if " " in name else f"cd {name}"
            results.append(Suggestion(formatted, f"Change to {name}"))
        return results[:12]
    except (OSError, PermissionError):
        return []


def local_suggestions(partial: str, cwd: str | os.PathLike[str] | None = None) -> list[Suggestion]:
    """Return fast, offline suggestions filtered against the partial command."""
    if not isinstance(partial, str) or len(partial) > MAX_COMMAND_LENGTH:
        return []
    value = partial.strip().casefold()
    directory = _safe_cwd(cwd)
    if value == "cd" or value.startswith("cd "):
        return _directory_suggestions(partial, directory)[:12]

    candidates = list(LOCAL_COMMANDS)
    result = [
        Suggestion(command, explanation)
        for command, explanation in candidates
        if not value or command.casefold().startswith(value)
    ]
    if value.startswith("git "):
        result = [item for item in result if item.command.startswith("git ")]
        for command, description in (
            ("git checkout", "Switch branches (execution disabled)"),
            ("git cherry-pick", "Apply a commit (execution disabled)"),
            ("git commit -m", "Record changes to repository"),
            ("git push", "Update remote refs"),
        ):
            if command.startswith(value):
                result.append(Suggestion(command, description))
    if value.startswith("pyth"):
        python_command = "py" if sys.platform == "win32" else "python3"
        result.append(Suggestion(f"{python_command} --version", "Show Python version"))
    result.extend(_directory_suggestions(partial, directory))
    unique: OrderedDict[str, Suggestion] = OrderedDict()
    for item in result:
        unique.setdefault(item.command, item)
    return list(unique.values())[:12]


def validate_command(command: str) -> tuple[list[str] | None, str]:
    """Validate and tokenize the deliberately limited command grammar for legacy runner tests."""
    if not isinstance(command, str) or not command.strip():
        return None, "Enter a command."
    if len(command) > MAX_COMMAND_LENGTH or "\x00" in command or "\n" in command or "\r" in command:
        return None, "Command is empty, too long, or contains invalid control characters."
    if _BLOCKED_PATTERNS.search(command):
        return None, "Shell operators and potentially dangerous commands are not supported."
    try:
        args = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        return None, "Could not parse command arguments."
    if not args:
        return None, "Enter a command."
    executable = Path(args[0]).name.casefold()
    if executable not in _ALLOWED_ROOTS:
        return None, "Command is not in the supported development command set."
    lowered = [arg.casefold() for arg in args]
    root = executable.removesuffix(".exe")
    if root in {"npm", "node"}:
        return None, "npm and Node script execution is not supported in the FocusOS terminal."
    if root in {"ls", "dir"} and any(part.startswith("-") and part not in {"-a", "-l", "-la", "-al", "-1", "/a", "/b", "/w"} for part in args[1:]):
        return None, "Unsupported directory-listing option."
    if root == "git" and (len(args) < 2 or args[1].casefold() not in {"status", "diff", "log", "show", "branch"}):
        return None, "Only read-only Git inspection commands are supported."
    if root in {"pip", "pip3"}:
        return None, "Direct pip commands are disabled in the FocusOS terminal."
    if root in {"python", "python3", "py"}:
        safe_python = {"--version", "-v", "--help", "-h"}
        if len(args) > 1 and (len(args) != 2 or args[1].casefold() not in safe_python):
            return None, "Python scripts, modules, package actions, and virtual environment creation are disabled in the FocusOS terminal."
    if root == "git" and any(arg in {"checkout", "cherry-pick", "reset", "clean", "switch", "merge", "rebase"} for arg in lowered[1:]):
        return None, "State-changing Git commands are not supported in the FocusOS terminal."
    if any(arg in {"--privileged", "--global", "--user"} for arg in lowered) and root in {"pip", "pip3", "npm"}:
        return None, "Global or privileged package operations are not supported."
    if root == "git" and any(arg in {"exec", "publish"} for arg in lowered[1:]):
        return None, "This operation is outside the supported safe command set."
    if root == "cd" and len(args) > 2:
        return None, "Use cd with at most one child directory."
    return args, ""


def execute_command(
    command: str,
    cwd: str | os.PathLike[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Execute a single tokenized safe command synchronously (legacy direct dispatch)."""
    args, error = validate_command(command)
    if error or args is None:
        return {"ok": False, "stdout": "", "stderr": error, "returncode": -1}
    working_dir = _safe_cwd(cwd)
    executable = Path(args[0]).name.casefold()
    if executable == "pwd":
        return {"ok": True, "stdout": str(working_dir), "stderr": "", "returncode": 0}
    if executable in {"ls", "dir"}:
        try:
            entries = sorted(working_dir.iterdir(), key=lambda entry: entry.name.casefold())
            return {
                "ok": True,
                "stdout": "\n".join(entry.name for entry in entries)[:MAX_OUTPUT_CHARS],
                "stderr": "",
                "returncode": 0,
            }
        except OSError as error_val:
            return {"ok": False, "stdout": "", "stderr": str(error_val)[:1000], "returncode": 1}
    if args[0].casefold() == "cd":
        try:
            requested = args[1] if len(args) > 1 else str(Path.home())
            target = filesystem_path(requested).expanduser()
            if not target.is_absolute():
                target = working_dir / target
            target = target.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            target = working_dir / "__inaccessible__"
        if not target.is_dir():
            return {"ok": False, "stdout": "", "stderr": "Directory is unavailable or inaccessible.", "returncode": -1}
        return {"ok": True, "stdout": str(target), "stderr": "", "returncode": 0, "cwd": str(target)}
    if args[0].casefold() in {"pip", "pip3"}:
        if any(part.casefold() in {"install", "uninstall", "download"} for part in args[1:]):
            return {
                "ok": False,
                "stdout": "",
                "stderr": "Package installation and mutation are disabled in the FocusOS terminal.",
                "returncode": -1,
            }
    try:
        completed = runner(
            args,
            cwd=str(working_dir),
            shell=False,
            capture_output=True,
            text=True,
            timeout=max(0.1, min(float(timeout), 30.0)),
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return {
            "ok": completed.returncode == 0,
            "stdout": (completed.stdout or "")[:16_000],
            "stderr": (completed.stderr or "")[:16_000],
            "returncode": completed.returncode,
        }
    except subprocess.TimeoutExpired as error_val:
        output = error_val.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return {
            "ok": False,
            "stdout": str(output)[:16_000],
            "stderr": "Command timed out and was terminated.",
            "returncode": -1,
        }
    except (OSError, ValueError) as error_val:
        return {"ok": False, "stdout": "", "stderr": str(error_val)[:1000], "returncode": -1}


class PTYSession:
    """Real pseudo-terminal session running an interactive system shell."""

    def __init__(
        self,
        cwd: str | Path | None = None,
        on_output: Callable[[str], None] | None = None,
        cols: int = 100,
        rows: int = 30,
        shell_preference: str | None = None,
    ):
        self.cwd = _safe_cwd(cwd)
        self.cols = cols
        self.rows = rows
        self.on_output = on_output
        self.shell_preference = shell_preference
        self.shell_path, self.shell_name = self._resolve_shell()
        self._pty: Any = None
        self._proc: subprocess.Popen[str] | None = None
        self._master_fd: int | None = None
        self._running = False
        self._reader_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.output_history: list[str] = []
        self._start()

    def _resolve_shell(self) -> tuple[str, str]:
        pref = (self.shell_preference or os.getenv("FOCUSOS_TERMINAL_SHELL", "")).strip().casefold()
        if sys.platform == "win32":
            if pref == "cmd":
                cmd = shutil.which("cmd.exe") or "cmd.exe"
                return cmd, "cmd"
            ps = shutil.which("powershell.exe")
            if ps and pref != "cmd":
                return ps, "powershell"
            cmd = shutil.which("cmd.exe") or "cmd.exe"
            return cmd, "cmd"
        else:
            shell = os.environ.get("SHELL") or shutil.which("bash") or shutil.which("sh") or "/bin/sh"
            name = Path(shell).name.casefold()
            return shell, name

    def _start(self) -> None:
        self._running = True
        if sys.platform == "win32" and _WINPTY_AVAILABLE:
            try:
                self._pty = winpty.PTY(self.cols, self.rows, backend=WinptyBackend.WinPTY)
                cmdline = "-NoLogo -NoProfile" if self.shell_name == "powershell" else None
                self._pty.spawn(self.shell_path, cmdline=cmdline, cwd=str(self.cwd))
            except Exception:
                self._pty = None
                self._spawn_fallback()
        elif sys.platform != "win32":
            try:
                import pty
                master, slave = pty.openpty()
                self._master_fd = master
                self._proc = subprocess.Popen(
                    [self.shell_path],
                    preexec_fn=os.setsid,
                    stdin=slave,
                    stdout=slave,
                    stderr=slave,
                    cwd=str(self.cwd),
                    close_fds=True,
                )
                os.close(slave)
            except Exception:
                self._spawn_fallback()
        else:
            self._spawn_fallback()

        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True, name="FocusOS-PTYReader")
        self._reader_thread.start()

    def _spawn_fallback(self) -> None:
        try:
            self._proc = subprocess.Popen(
                [self.shell_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(self.cwd),
                bufsize=1,
            )
        except Exception:
            self._proc = None

    def _reader_loop(self) -> None:
        while self._running:
            try:
                chunk = ""
                if self._pty is not None:
                    chunk = self._pty.read(blocking=False)
                    if not chunk:
                        time.sleep(0.02)
                        continue
                elif self._master_fd is not None:
                    import select
                    r, _, _ = select.select([self._master_fd], [], [], 0.05)
                    if r:
                        raw = os.read(self._master_fd, 4096)
                        if raw:
                            chunk = raw.decode("utf-8", errors="replace")
                        else:
                            break
                    else:
                        continue
                elif self._proc is not None and self._proc.stdout is not None:
                    line = self._proc.stdout.readline()
                    if line:
                        chunk = line
                    else:
                        time.sleep(0.02)
                        continue
                else:
                    break

                if chunk:
                    clean = strip_ansi(chunk)
                    with self._lock:
                        self.output_history.append(clean)
                        if len(self.output_history) > 1000:
                            self.output_history = self.output_history[-800:]
                    if self.on_output:
                        try:
                            self.on_output(clean)
                        except Exception:
                            pass
            except Exception:
                break

    def write(self, data: str) -> None:
        if not self._running:
            return
        try:
            if self._pty is not None:
                self._pty.write(data)
            elif self._master_fd is not None:
                os.write(self._master_fd, data.encode("utf-8"))
            elif self._proc is not None and self._proc.stdin is not None:
                self._proc.stdin.write(data)
                self._proc.stdin.flush()
        except (OSError, Exception):
            pass

    def write_command(self, command: str) -> None:
        newline = "\r\n" if sys.platform == "win32" else "\n"
        self.write(command + newline)

    def send_interrupt(self) -> None:
        """Send SIGINT / Ctrl+C (0x03) to the running process."""
        self.write("\x03")

    def resize(self, cols: int, rows: int) -> None:
        self.cols = cols
        self.rows = rows
        if self._pty is not None:
            try:
                self._pty.set_size(cols, rows)
            except Exception:
                pass

    def set_cwd(self, path: Path | str) -> tuple[bool, str]:
        """Validate directory permissions and switch terminal cwd."""
        try:
            target = filesystem_path(path).expanduser()
            if not target.is_absolute():
                target = (self.cwd / target).resolve()
            else:
                target = target.resolve()
        except Exception as error_val:
            return False, f"Invalid path: {error_val}"

        if not target.exists():
            return False, f"Directory does not exist: {target}"
        if not target.is_dir():
            return False, f"Path is not a directory: {target}"
        if not os.access(target, os.R_OK | os.X_OK):
            return False, f"Permission denied: cannot access directory {target}"

        self.cwd = target
        if self.shell_name == "powershell":
            self.write_command(f'Set-Location -LiteralPath "{target}"')
        elif sys.platform == "win32":
            self.write_command(f'cd /d "{target}"')
        else:
            self.write_command(f'cd "{target}"')
        return True, str(target)

    def restart(self, cwd: Path | str | None = None) -> None:
        """Restart shell cleanly in the target directory."""
        self.terminate()
        if cwd is not None:
            self.cwd = _safe_cwd(cwd)
        self._start()

    def terminate(self) -> None:
        self._running = False
        if self._pty is not None:
            try:
                pid = getattr(self._pty, "pid", None)
                if pid:
                    import psutil
                    try:
                        p = psutil.Process(pid)
                        for child in p.children(recursive=True):
                            try:
                                child.kill()
                            except Exception:
                                pass
                        p.kill()
                    except Exception:
                        pass
                del self._pty
            except Exception:
                pass
            self._pty = None

        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.kill()
            except Exception:
                pass
            self._proc = None

        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except Exception:
                pass
            self._master_fd = None


class HuggingFaceSuggester:
    """Hugging Face Inference client for real-time autocomplete and assistant commands."""

    def __init__(
        self,
        token: str | None = None,
        model_id: str | None = None,
        api_url: str | None = None,
        timeout: float = AI_TIMEOUT_SECONDS,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ):
        self.token = (token if token is not None else os.getenv("HF_TOKEN", "")).strip()
        self.model_id = (model_id if model_id is not None else os.getenv("HF_MODEL_ID", "")).strip()
        self.api_url = (api_url if api_url is not None else os.getenv("HF_API_URL", "")).strip()
        self.timeout = min(max(float(timeout), 0.1), AI_TIMEOUT_SECONDS)
        self.opener = opener
        self._cache: OrderedDict[tuple[str, str], list[Suggestion]] = OrderedDict()
        self._assistant_cache: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()

    @property
    def available(self) -> bool:
        return bool(self.token and self.model_id)

    def suggest(self, partial: str, cwd: str, platform: str, intent: str = "") -> list[Suggestion]:
        if not self.available or not partial.strip() or len(partial) > MAX_COMMAND_LENGTH:
            return []
        key = (partial.strip().casefold(), intent.strip().casefold())
        if key in self._cache:
            self._cache.move_to_end(key)
            return list(self._cache[key])
        endpoint = self.api_url or f"https://router.huggingface.co/hf-inference/models/{self.model_id}"
        natural_language = intent.strip() or partial.strip()
        prompt = (
            "Translate the user's natural-language request into at most 3 safe, read-only "
            "local development terminal commands. Return ONLY a JSON array of objects with "
            '"command" and "explanation". No markdown, shell chaining, scripts, '
            "destructive actions, network changes, or package installation. If the request "
            "cannot be fulfilled safely, return an empty array. "
            f"OS/shell: {platform}. Working directory: {Path(cwd).name}. "
            f"User request: {natural_language[:240]}"
        )
        payload = json.dumps({"inputs": prompt, "parameters": {"max_new_tokens": 160, "return_full_text": False}}).encode()
        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read(16_384)
            decoded = json.loads(raw.decode("utf-8"))
            text = (
                decoded[0].get("generated_text", "")
                if isinstance(decoded, list) and decoded
                else decoded.get("generated_text", "")
                if isinstance(decoded, dict)
                else ""
            )
            if not isinstance(text, str):
                return []
            match = re.search(r"\[.*\]", text, re.DOTALL)
            values = json.loads(match.group(0)) if match else []
            results = []
            for entry in values[:3] if isinstance(values, list) else []:
                if not isinstance(entry, dict):
                    continue
                command = entry.get("command")
                explanation = entry.get("explanation", "AI suggestion; review before execution")
                if not isinstance(command, str) or not isinstance(explanation, str):
                    continue
                args, error = validate_command(command)
                if args is not None and not error:
                    results.append(Suggestion(command, explanation[:180], "ai"))
            self._cache[key] = results
            if len(self._cache) > 64:
                self._cache.popitem(last=False)
            return results
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, TypeError, KeyError):
            return []

    def generate_assistant_commands(
        self, prompt: str, cwd: str, platform: str, shell: str
    ) -> dict[str, Any]:
        """Generate multi-step shell commands for a natural language user request."""
        clean_prompt = prompt.strip()
        if not clean_prompt or len(clean_prompt) > MAX_COMMAND_LENGTH:
            return {"ok": False, "error": "Enter a request under 1024 characters.", "steps": [], "commands": []}
        cache_key = (clean_prompt.casefold(), platform.casefold())
        if cache_key in self._assistant_cache:
            self._assistant_cache.move_to_end(cache_key)
            return dict(self._assistant_cache[cache_key])

        # Check Hugging Face first if available
        if self.available:
            endpoint = self.api_url or f"https://router.huggingface.co/hf-inference/models/{self.model_id}"
            instruction = (
                f"You are a careful assistant for a restricted development terminal on {platform} "
                f"using {shell}, in working directory {Path(cwd).name}. User request: "
                f"\"{clean_prompt[:240]}\". Return ONLY a JSON array with one object "
                'containing "command" and "explanation". Use exactly one read-only command '
                "from this set: git status, git diff, git log, git branch, pwd, ls -la, dir, "
                "python --version, pytest -v. Do not return shell scripts, operators, package "
                "changes, file changes, network commands, or destructive commands. If no "
                "listed command satisfies the request, return []."
            )
            payload = json.dumps(
                {"inputs": instruction, "parameters": {"max_new_tokens": 300, "return_full_text": False}}
            ).encode()
            request = urllib.request.Request(
                endpoint,
                data=payload,
                headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
                method="POST",
            )
            try:
                with self.opener(request, timeout=self.timeout) as resp:
                    raw = resp.read(32_768)
                data = json.loads(raw.decode("utf-8"))
                text = (
                    data[0].get("generated_text", "")
                    if isinstance(data, list) and data
                    else data.get("generated_text", "")
                    if isinstance(data, dict)
                    else ""
                )
                match = re.search(r"\[.*\]", text, re.DOTALL)
                if match:
                    parsed_steps = json.loads(match.group(0))
                    if isinstance(parsed_steps, list):
                        safe_steps = []
                        for item in parsed_steps[:3]:
                            if not isinstance(item, dict):
                                continue
                            command = item.get("command")
                            explanation = item.get("explanation", "AI suggestion; review before execution")
                            if not isinstance(command, str) or not isinstance(explanation, str):
                                continue
                            args, error = validate_command(command)
                            if args is not None and not error:
                                safe_steps.append({
                                    "step": len(safe_steps) + 1,
                                    "command": command,
                                    "description": explanation[:180],
                                })
                        if safe_steps:
                            commands = [item["command"] for item in safe_steps]
                            result = {
                                "ok": True,
                                "prompt": clean_prompt,
                                "commands": commands,
                                "steps": safe_steps,
                                "is_destructive": False,
                                "warning": "",
                                "source": "hf",
                            }
                            self._assistant_cache[cache_key] = dict(result)
                            if len(self._assistant_cache) > 64:
                                self._assistant_cache.popitem(last=False)
                            return result
            except Exception:
                pass  # Fall through to robust local heuristic generator

        # Smart local heuristic generator for offline & reliable operation
        result = self._generate_heuristic_commands(clean_prompt, cwd, platform, shell)
        if result.get("ok") and result.get("commands"):
            safe_commands = []
            for command in result["commands"][:3]:
                args, error = validate_command(command)
                if args is not None and not error:
                    safe_commands.append(command)
            if safe_commands:
                result["commands"] = safe_commands
                result["steps"] = [
                    {"step": index, "command": command, "description": "Run the matching safe terminal command"}
                    for index, command in enumerate(safe_commands, 1)
                ]
                self._assistant_cache[cache_key] = dict(result)
                if len(self._assistant_cache) > 64:
                    self._assistant_cache.popitem(last=False)
                return result
        result = {"ok": False, "error": "I couldn't map that request to a supported safe command. Try asking to list files, show the current directory, or check repository status.", "steps": [], "commands": []}
        self._assistant_cache[cache_key] = dict(result)
        if len(self._assistant_cache) > 64:
            self._assistant_cache.popitem(last=False)
        return result

    def _generate_heuristic_commands(
        self, prompt: str, cwd: str, platform: str, shell: str
    ) -> dict[str, Any]:
        """Reliable rule-based generator for development requests."""
        p_lower = prompt.casefold()
        if any(term in p_lower for term in (
            "delete", "remove", "erase", "format", "overwrite", "modify", "change file",
            "edit file", "write file", "install", "uninstall", "commit", "push", "pull",
            "create", "generate", "build", "deploy", "shutdown", "kill process",
        )):
            return {
                "ok": False,
                "error": "This request could change files, system state, or external resources, so the restricted terminal will not run it.",
                "steps": [],
                "commands": [],
            }
        steps = []
        commands = []
        is_windows = platform.casefold().startswith("win") or sys.platform == "win32"
        is_ps = "power" in shell.casefold()
        if any(term in p_lower for term in (
            "delete", "remove", "erase", "format", "overwrite", "modify", "change file",
            "edit file", "write file", "install", "uninstall", "commit", "push", "pull",
            "create", "generate", "build", "deploy", "shutdown", "kill process",
        )):
            return {
                "ok": False,
                "error": "This request could change files, system state, or external resources, so the restricted terminal will not run it.",
                "steps": [],
                "commands": [],
            }

        if "virtual environment" in p_lower or "venv" in p_lower:
            py = "python" if is_windows else "python3"
            steps.append({"step": 1, "command": f"{py} -m venv .venv", "description": "Create a virtual environment named .venv"})
            commands.append(f"{py} -m venv .venv")

            if is_windows:
                act = r".\.venv\Scripts\Activate.ps1" if is_ps else r".\.venv\Scripts\activate.bat"
            else:
                act = "source .venv/bin/activate"
            steps.append({"step": 2, "command": act, "description": "Activate the virtual environment"})
            commands.append(act)

            if "requirement" in p_lower or "install" in p_lower:
                steps.append({"step": 3, "command": "pip install -r requirements.txt", "description": "Install requirements from requirements.txt"})
                commands.append("pip install -r requirements.txt")

        elif "test" in p_lower or "pytest" in p_lower:
            cmd = "git status" if "run" not in p_lower and "execute" not in p_lower and "check" not in p_lower else "pytest -v"
            steps.append({"step": 1, "command": cmd, "description": "Run the test suite with verbose output"})
            commands.append(cmd)

        elif "git" in p_lower and ("status" in p_lower or "check" in p_lower):
            steps.append({"step": 1, "command": "git status", "description": "Inspect repository working tree"})
            commands.append("git status")
            if "diff" in p_lower or "change" in p_lower:
                steps.append({"step": 2, "command": "git diff", "description": "Inspect unstaged file changes"})
                commands.append("git diff")


        elif any(word in p_lower for word in ("list", "directory", "folder", "files", "contents", "show me what's in", "what is in")):
            cmd = "dir" if is_windows else "ls -la"
            steps.append({"step": 1, "command": cmd, "description": "List files in the current working directory"})
            commands.append(cmd)

        elif any(word in p_lower for word in ("current directory", "working directory", "where am i", "current folder", "show path", "what path", "print path")):
            steps.append({"step": 1, "command": "pwd", "description": "Show the current working directory"})
            commands.append("pwd")

        elif "git" in p_lower and any(word in p_lower for word in ("branch", "branches")):
            steps.append({"step": 1, "command": "git branch", "description": "List local Git branches"})
            commands.append("git branch")

        elif "git" in p_lower and any(word in p_lower for word in ("history", "commits", "log", "recent")):
            steps.append({"step": 1, "command": "git log", "description": "Show recent Git commits"})
            commands.append("git log")

        elif "git" in p_lower and any(word in p_lower for word in ("diff", "changes", "changed files")):
            steps.append({"step": 1, "command": "git diff", "description": "Show unstaged Git changes"})
            commands.append("git diff")

        elif "python" in p_lower and any(word in p_lower for word in ("version", "installed")):
            cmd = "python --version" if is_windows else "python3 --version"
            steps.append({"step": 1, "command": cmd, "description": "Show the Python version"})
            commands.append(cmd)

        elif any(word in p_lower for word in ("repository", "repo", "git")) and any(word in p_lower for word in ("status", "check", "clean", "changes")):
            steps.append({"step": 1, "command": "git status", "description": "Inspect repository working tree"})
            commands.append("git status")

        else:
            return {
                "ok": False,
                "error": "I couldn't map that request to a supported safe command. Try asking to list files, show the current directory, check Git status, view recent commits, or run tests.",
                "steps": [],
                "commands": [],
            }

        is_destr = any(is_destructive_command(c) for c in commands)
        warning = "Caution: Destructive command detected! This action may alter or delete files." if is_destr else ""

        return {
            "ok": True,
            "prompt": prompt,
            "commands": commands,
            "steps": steps,
            "is_destructive": is_destr,
            "warning": warning,
            "source": "local_heuristic",
        }


class TerminalService:
    """Manages terminal session state, execution, autocomplete, and AI integration."""

    def __init__(
        self,
        cwd: str | None = None,
        suggester: HuggingFaceSuggester | None = None,
        on_output: Callable[[str], None] | None = None,
    ):
        self.cwd = str(_safe_cwd(cwd))
        self.suggester = suggester or HuggingFaceSuggester()
        self.history: list[str] = []
        self._suggestion_id = 0
        self._lock = threading.Lock()
        self._ai_suggestions: list[Suggestion] = []
        self.output_buffer: list[str] = []
        self.on_output = on_output
        self.pty: PTYSession = PTYSession(cwd=self.cwd, on_output=self._handle_pty_output)

    @property
    def ai_available(self) -> bool:
        return self.suggester.available

    @property
    def platform_name(self) -> str:
        shell_label = "PowerShell" if self.pty.shell_name == "powershell" else "Command Prompt" if self.pty.shell_name == "cmd" else self.pty.shell_name.capitalize()
        os_label = "Windows" if sys.platform == "win32" else "Linux" if sys.platform.startswith("linux") else "macOS"
        return f"{os_label} ({shell_label})"

    def _handle_pty_output(self, text: str) -> None:
        with self._lock:
            self.output_buffer.append(text)
            if len(self.output_buffer) > 2000:
                self.output_buffer = self.output_buffer[-1500:]
        if self.on_output:
            try:
                self.on_output(text)
            except Exception:
                pass

    def suggestions(self, partial: str) -> list[Suggestion]:
        local = local_suggestions(partial, self.cwd)
        with self._lock:
            ai = list(self._ai_suggestions)
        return (local + ai)[:15]

    def request_ai(self, partial: str, intent: str, callback: Callable[[list[Suggestion]], None]) -> None:
        if not self.ai_available or len(partial) > MAX_COMMAND_LENGTH:
            callback([])
            return
        with self._lock:
            self._suggestion_id += 1
            request_id = self._suggestion_id

        def work() -> None:
            items = self.suggester.suggest(partial, self.cwd, sys.platform, intent)
            with self._lock:
                if request_id != self._suggestion_id:
                    return
                self._ai_suggestions = items
            callback(items)

        threading.Thread(target=work, daemon=True, name="FocusOS-AI-suggestions").start()

    def invalidate_ai(self) -> None:
        with self._lock:
            self._suggestion_id += 1
            self._ai_suggestions = []

    def generate_ai_assistant_commands(self, prompt: str) -> dict[str, Any]:
        """Request multi-step command generation from AI or smart local templates."""
        return self.suggester.generate_assistant_commands(
            prompt, self.cwd, sys.platform, self.pty.shell_name
        )

    def set_cwd(self, path: str | Path) -> tuple[bool, str]:
        """Change directory, validate access, and update PTY session."""
        success, resolved_or_error = self.pty.set_cwd(path)
        if success:
            self.cwd = resolved_or_error
            self.invalidate_ai()
        return success, resolved_or_error

    def run_pty_command(self, command: str) -> None:
        """Execute command in the live PTY shell session."""
        clean = command.strip()
        if not clean:
            return
        if clean not in self.history:
            self.history.append(clean)
        self.history = self.history[-MAX_HISTORY:]
        self.pty.write_command(clean)

    def send_input(self, text: str) -> None:
        """Send keystrokes directly to the PTY."""
        self.pty.write(text)

    def send_interrupt(self) -> None:
        """Interrupt active process in the PTY."""
        self.pty.send_interrupt()

    def clear(self) -> None:
        with self._lock:
            self.output_buffer.clear()

    @staticmethod
    def validate(command: str) -> tuple[list[str] | None, str]:
        return validate_command(command)

    def execute(self, command: str, confirmed: bool = False) -> dict[str, Any]:
        """Legacy direct executor for unit tests."""
        args, error = validate_command(command)
        if error or args is None:
            return {"ok": False, "stdout": "", "stderr": error, "returncode": -1}
        if not confirmed:
            return {
                "ok": False,
                "stdout": "",
                "stderr": "Confirm execution before running a command.",
                "returncode": -1,
                "confirmation_required": True,
            }
        result = execute_command(command, self.cwd)
        if result.get("ok"):
            if command not in self.history:
                self.history.append(command)
            self.history = self.history[-MAX_HISTORY:]
            if args[0].casefold() == "cd" and result.get("cwd"):
                self.cwd = str(result["cwd"])
                self.pty.set_cwd(self.cwd)
        return result

    def dispose(self) -> None:
        """Clean up PTY processes and threads."""
        self.pty.terminate()
