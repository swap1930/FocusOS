"""Behavior and security tests for the FocusOS terminal module."""

import io
import json
import subprocess
from pathlib import Path
import urllib.error
from ai.terminal import (
    CohereSuggester,
    TerminalService,
    execute_command,
    filesystem_path,
    local_suggestions,
    validate_command,
    validate_ai_command,
    is_destructive_command,
)


def test_local_autocomplete_git_and_python():
    assert "git status" in {item.command for item in local_suggestions("git sta")}
    assert "git checkout" in {item.command for item in local_suggestions("git che")}
    assert local_suggestions("pyth")


def test_directory_suggestions_are_limited_to_children(tmp_path, monkeypatch):
    (tmp_path / "work").mkdir()
    import ai.terminal as terminal_module
    monkeypatch.setattr(terminal_module, "_safe_cwd", lambda candidate=None: tmp_path)
    assert [item.command for item in local_suggestions("cd", tmp_path)] == ["cd work"]
    assert [item.command for item in local_suggestions("cd wo", tmp_path)] == ["cd work"]
    assert local_suggestions("cd ..", tmp_path) == []


def test_selected_working_directory_can_be_outside_project(tmp_path):
    selected = tmp_path / "chosen"
    selected.mkdir()
    from ai.terminal import TerminalService
    service = TerminalService(cwd=str(selected))
    assert service.cwd == str(selected.resolve())
    submitted = []
    service.pty.write_command = submitted.append
    assert service.execute("cd ..", confirmed=True, additional_confirmed=True)["submitted_to_pty"]
    assert submitted == ["cd .."]


def test_terminal_execute_submits_arbitrary_command_to_live_pty(tmp_path, monkeypatch):
    from ai.terminal import TerminalService
    service = TerminalService(cwd=str(tmp_path))
    submitted = []
    monkeypatch.setattr(service.pty, "write_command", submitted.append)
    result = service.execute('cd "missing folder"', confirmed=True, additional_confirmed=True)
    assert result["submitted_to_pty"]
    assert submitted == ['cd "missing folder"']


def test_picker_file_url_converts_to_filesystem_path(tmp_path):
    chosen = tmp_path / "chosen folder"
    chosen.mkdir()
    assert filesystem_path(chosen.as_uri()) == chosen


def test_windows_drive_path_is_not_mistaken_for_a_url():
    assert filesystem_path(r"D:\\Work Folder\\Project") == Path(r"D:\\Work Folder\\Project")


def test_legacy_executor_is_not_used_for_arbitrary_commands():
    result = execute_command("npm install", Path.cwd())
    assert not result["ok"]


def test_prompt_classifier_routes_natural_language_and_arbitrary_shell_commands():
    import ast
    import os
    import re
    import shlex
    import shutil
    from pathlib import Path
    source_path = Path(__file__).resolve().parents[1] / "dashboard_qml.py"
    source = source_path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source)
    backend = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "DashboardBackend")
    method = next(node for node in backend.body if isinstance(node, ast.FunctionDef) and node.name == "_looks_like_shell_command")
    module = ast.Module(body=[method], type_ignores=[])
    namespace = {"re": re, "shlex": shlex, "shutil": shutil, "os": os}
    exec(compile(module, str(source_path), "exec"), namespace)
    looks_like_shell = namespace["_looks_like_shell_command"].__func__
    assert not looks_like_shell("check the folders")
    assert not looks_like_shell("create a Python file")
    assert not looks_like_shell("check")
    assert looks_like_shell("git status")
    assert looks_like_shell("python script.py")
    assert looks_like_shell("mkdir app && cd app")
    assert looks_like_shell("my-custom-tool --version")
    assert looks_like_shell("./custom-tool")


def test_validation_accepts_arbitrary_shell_commands_and_syntax():
    for command in (
        "git status; whoami", "rm -rf .", "sudo python x.py", "python x.py | cat",
        "powershell -Command Write-Output ok", "git checkout main", "npm run test",
        "pip install requests", "touch new_file.py", "python script.py",
        "mkdir app && cd app && npm init -y", "Remove-Item -Recurse build",
    ):
        args, error = validate_command(command)
        assert args is not None and not error
        assert validate_ai_command(command) == (True, "")


def test_execution_timeout_and_output_limits(tmp_path):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"], output="partial")
    assert "timed out" in execute_command("git status", tmp_path, runner=timeout)["stderr"]
    class Large:
        returncode = 0
        stdout = "x" * 30_000
        stderr = ""
    assert len(execute_command("git status", tmp_path, runner=lambda *a, **k: Large())["stdout"]) <= 16_000


def test_terminal_execute_submits_without_confirmation(monkeypatch):
    service = TerminalService()
    submitted = []
    monkeypatch.setattr(service.pty, "write_command", submitted.append)
    result = service.execute("npm install")
    assert result["submitted_to_pty"]
    assert submitted == ["npm install"]


def test_cohere_client_requires_api_key(monkeypatch):
    monkeypatch.setenv("COHERE_API_KEY", "")
    client = CohereSuggester()
    assert not client.available
    assert client.suggest("git sta", ".", "linux") == []


def test_cohere_timeout_and_api_failures_return_empty():
    def timeout(*args, **kwargs):
        raise TimeoutError("slow")
    client = CohereSuggester(api_key="test-key", opener=timeout)
    assert client.suggest("git sta", ".", "linux") == []
    result = client.generate_assistant_commands("check git status", ".", "linux", "bash")
    assert "slow" in result["error"]
    def unavailable(*args, **kwargs):
        raise urllib.error.HTTPError("url", 503, "unavailable", None, None)
    client = CohereSuggester(api_key="test-key", opener=unavailable)
    assert client.suggest("git sta", ".", "linux") == []


def test_cohere_v2_chat_request_and_response():
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit):
            return json.dumps({"message": {"content": [{"type": "text", "text": '[{"command":"git status","explanation":"Check status"}]'}]}}).encode()

    captured = {}

    def opener(request, **kwargs):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data)
        captured["content_type"] = request.get_header("Content-type")
        captured["authorization"] = request.get_header("Authorization")
        return Response()

    client = CohereSuggester(api_key="test-key", model_id="command-a-03-2025", opener=opener)
    result = client.generate_assistant_commands("check git status", ".", "linux", "bash")
    assert result["ok"]
    assert result["commands"] == ["git status"]
    assert captured["url"] == "https://api.cohere.com/v2/chat"
    assert captured["payload"]["model"] == "command-a-03-2025"
    assert captured["payload"]["messages"][0]["role"] == "system"
    assert captured["payload"]["messages"][1]["role"] == "user"
    assert captured["payload"]["max_tokens"] == 4096
    assert captured["payload"]["temperature"] == 0
    assert captured["payload"]["stream"] is False
    assert captured["content_type"] == "application/json"
    assert captured["authorization"] == "Bearer test-key"


def test_cohere_http_error_includes_service_detail_without_key():
    def rejected(request, **kwargs):
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", {},
            io.BytesIO(b'{"message":"invalid api token"}'),
        )

    client = CohereSuggester(api_key="test-key", opener=rejected)
    result = client.generate_assistant_commands("check git status", ".", "linux", "bash")
    assert not result["ok"]
    assert "HTTP 401" in result["error"]
    assert "invalid api token" in result["error"]
    assert "test-key" not in result["error"]


def test_cohere_suggestions_support_unrestricted_command_but_mark_risk():
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit):
            return json.dumps({"message": {"content": [{"type": "text", "text": '[{"command":"git status","explanation":"Check status"},{"command":"rm -rf .","explanation":"bad"}]'}]}}).encode()
    client = CohereSuggester(api_key="test-key", opener=lambda *a, **k: Response())
    values = client.suggest("show status", ".", "linux")
    assert [item.command for item in values] == ["git status", "rm -rf ."]
    assert "High-impact" in values[1].explanation


def test_platform_interpreter_commands_validate():
    assert validate_command("python --version")[0] == ["python", "--version"]
    assert validate_command("python3 --version")[0] == ["python3", "--version"]


def test_natural_language_requests_require_cohere_configuration(monkeypatch):
    monkeypatch.setenv("COHERE_API_KEY", "")
    client = CohereSuggester()
    result = client.generate_assistant_commands("please check git status", ".", "linux", "bash")
    assert not result["ok"]
    assert "COHERE_API_KEY" in result["error"]
    assert result["commands"] == []
    assert client._generate_heuristic_commands("please check git status", ".", "linux", "bash")["commands"] == ["git status"]


def test_ai_navigation_is_generated_and_validated_by_language_model(tmp_path):
    target = tmp_path / "Folder With Spaces"
    target.mkdir()

    class Response:
        def __init__(self, command):
            self.command = command
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit):
            return json.dumps({"message": {"content": [{"type": "text", "text": json.dumps([{
                "command": self.command,
                "explanation": "Navigate to the requested folder",
            }])}]}}).encode()

    good = CohereSuggester(
        api_key="test-key",
        opener=lambda *a, **k: Response(f'cd "{target}"'),
    )
    navigation = good.generate_assistant_commands(
        f'move to folder "{target}"', str(tmp_path), "windows", "powershell"
    )
    assert navigation["ok"]
    assert navigation["commands"] == [f'cd "{target}"']

    rejected_command = CohereSuggester(
        api_key="test-key",
        opener=lambda *a, **k: Response('cd ".."'),
    )
    rejected = rejected_command.generate_assistant_commands(
        f'move to folder "{target}"', str(tmp_path), "windows", "powershell"
    )
    assert rejected["ok"]
    assert rejected["commands"] == ['cd ".."']


def test_ai_navigation_commands_are_previewed_for_user_confirmation(tmp_path):
    target = tmp_path / "Folder With Spaces"
    target.mkdir()
    command = f'cd "{target}"'
    client = CohereSuggester(
        api_key="test-key",
        opener=lambda *args, **kwargs: _cohere_response_for([{
            "command": command,
            "explanation": "Navigate to the requested folder",
        }])(),
    )
    result = client.generate_assistant_commands(
        f'move to folder "{target}"', str(tmp_path), "windows", "powershell"
    )
    assert result["ok"]
    assert result["commands"] == [command]



def _cohere_response_for(steps):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit):
            text = json.dumps(steps)
            return json.dumps({"message": {"content": [{"type": "text", "text": text}]}}).encode()
    return Response


def test_ai_assistant_rejects_multiple_commands_instead_of_running_a_list():
    generated = [
        {"command": "pip install requests", "explanation": "Install dependency"},
        {"command": "python scripts/setup.py", "explanation": "Run setup script"},
    ]
    client = CohereSuggester(api_key="test-key", opener=lambda *a, **k: _cohere_response_for(generated)())
    result = client.generate_assistant_commands("set up the project", ".", "linux", "bash")
    assert not result["ok"]
    assert result["commands"] == []
    assert "exactly one command" in result["error"]


def test_ai_response_marks_destructive_single_command_without_confirmation():
    generated = [{"command": "rm -rf build", "explanation": "Remove generated files"}]
    client = CohereSuggester(api_key="test-key", opener=lambda *a, **k: _cohere_response_for(generated)())
    result = client.generate_assistant_commands("clean generated files", ".", "linux", "bash")
    assert result["ok"]
    assert result["is_destructive"]
    assert not result["requires_additional_confirmation"]
    assert "automatically" in result["warning"]


def test_pty_command_lock_rejects_parallel_command(monkeypatch):
    service = TerminalService()
    submitted = []

    def write_command(command, on_complete=None):
        with service.pty._command_lock:
            if service.pty._command_active:
                return False
            service.pty._command_active = True
            service.pty._on_command_complete = on_complete
            service.pty._command_done_token = "DONE"
        submitted.append(command)
        return True

    monkeypatch.setattr(service.pty, "write_command", write_command)
    completed = []
    assert service.run_pty_command("first command", on_complete=lambda: completed.append(True))
    assert not service.run_pty_command("second command")
    assert submitted == ["first command"]
    service.pty._complete_active_command()
    assert completed == [True]
    assert service.run_pty_command("second command")
    assert submitted == ["first command", "second command"]


def test_destructive_commands_are_detected_across_supported_shells():
    for command in (
        "rm -rf build", "Remove-Item -Recurse build", "rmdir /s build",
        "git reset --hard", "git push --force", "shutdown.exe /s",
    ):
        assert is_destructive_command(command), command
