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
    result = service.execute("cd ..", confirmed=True)
    assert result["ok"]
    assert service.cwd == str(tmp_path.resolve())


def test_terminal_selected_directory_must_exist_and_be_a_directory(tmp_path):
    from ai.terminal import TerminalService
    service = TerminalService()
    assert not service.execute("cd " + str(tmp_path / "missing"), confirmed=True)["ok"]
    file_path = tmp_path / "file.txt"
    file_path.write_text("not a directory")
    assert not service.execute("cd " + str(file_path), confirmed=True)["ok"]


def test_picker_file_url_converts_to_filesystem_path(tmp_path):
    chosen = tmp_path / "chosen folder"
    chosen.mkdir()
    assert filesystem_path(chosen.as_uri()) == chosen


def test_windows_drive_path_is_not_mistaken_for_a_url():
    assert filesystem_path(r"D:\\Work Folder\\Project") == Path(r"D:\\Work Folder\\Project")


def test_selected_directory_is_used_by_following_commands(tmp_path):
    selected = tmp_path / "selected"
    selected.mkdir()
    service = TerminalService(cwd=str(selected))
    result = service.execute("pwd", confirmed=True)
    assert result["ok"]
    assert Path(result["stdout"].strip()) == selected.resolve()
    (selected / "visible.txt").write_text("directory listing test")
    listing = service.execute("dir", confirmed=True)
    assert listing["ok"]
    assert "visible.txt" in listing["stdout"].splitlines()


def test_input_validation_blocks_shell_operators_and_unsafe_commands():
    assert validate_command("git status")[0] == ["git", "status"]
    for command in ("git status; whoami", "rm -rf .", "sudo python x.py", "python x.py | cat",
                    "powershell -Command x", "git checkout main", "npm run test"):
        assert validate_command(command)[1]


def test_execution_uses_argument_array_without_shell(tmp_path):
    calls = {}
    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""
    def runner(args, **kwargs):
        calls["args"] = args
        calls.update(kwargs)
        return Result()
    result = execute_command("git status", tmp_path, runner=runner)
    assert result["ok"]
    assert calls["shell"] is False
    assert calls["args"] == ["git", "status"]


def test_execution_timeout_and_output_limits(tmp_path):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"], output="partial")
    assert "timed out" in execute_command("git status", tmp_path, runner=timeout)["stderr"]
    class Large:
        returncode = 0
        stdout = "x" * 30_000
        stderr = ""
    assert len(execute_command("git status", tmp_path, runner=lambda *a, **k: Large())["stdout"]) <= 16_000


def test_terminal_requires_confirmation_and_disables_package_install():
    service = TerminalService()
    assert service.execute("git status")["confirmation_required"]
    assert "ok" in service.execute("git status", confirmed=True)
    assert "disabled" in service.execute("pip install requests", confirmed=True)["stderr"]
    assert "not supported" in service.execute("npm run test", confirmed=True)["stderr"]


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
    assert captured["url"] == "https://api.cohere.com/v2/chat"
    assert captured["payload"]["model"] == "command-a-03-2025"
    assert captured["payload"]["messages"][0]["role"] == "system"
    assert captured["payload"]["messages"][1]["role"] == "user"
    assert captured["payload"]["max_tokens"] == 300
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


def test_cohere_filters_untrusted_generated_commands():
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit):
            return json.dumps({"message": {"content": [{"type": "text", "text": '[{"command":"git status","explanation":"Check status"},{"command":"rm -rf .","explanation":"bad"}]'}]}}).encode()
    client = CohereSuggester(api_key="test-key", opener=lambda *a, **k: Response())
    values = client.suggest("show status", ".", "linux")
    assert [item.command for item in values] == ["git status"]


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
    assert not rejected["ok"]
    assert rejected["commands"] == []


def test_ai_navigation_validator_supports_windows_paths_with_spaces(tmp_path):
    from ai.terminal import _validate_ai_navigation

    target = tmp_path / "Folder With Spaces"
    target.mkdir()
    windows_path = str(target).replace("/", "\\")
    command = f'cd "{windows_path}"'
    assert _validate_ai_navigation(command, f'move to folder "{windows_path}"', tmp_path)
    assert not _validate_ai_navigation(f'{command}; whoami', f'move to folder "{windows_path}"', tmp_path)
    assert not _validate_ai_navigation('cd "missing folder"', 'move to folder "missing folder"', tmp_path)


def test_ai_navigation_validator_supports_linux_paths_and_rejects_invalid_targets(tmp_path):
    from ai.terminal import _validate_ai_navigation

    target = tmp_path / "linux folder"
    target.mkdir()
    command = f'cd "{target}"'
    assert _validate_ai_navigation(command, f'move to folder "{target}"', tmp_path)
    assert not _validate_ai_navigation('cd "missing folder"', 'move to folder "missing folder"', tmp_path)
    assert not _validate_ai_navigation(command, f'move to folder "{tmp_path / "other"}"', tmp_path)


def test_ai_assistant_response_rejects_command_injection():
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit):
            return json.dumps({"message": {"content": [{"type": "text", "text": '[{"command":"git status; whoami","explanation":"unsafe"}]'}]}}).encode()

    client = CohereSuggester(api_key="test-key", opener=lambda *a, **k: Response())
    result = client.generate_assistant_commands("check repository", ".", "linux", "bash")
    assert not result["ok"]
    assert result["commands"] == []


def test_ai_assistant_response_rejects_non_allowlisted_command():
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit):
            return json.dumps({"message": {"content": [{"type": "text", "text": '[{"command":"rm -rf .","explanation":"unsafe"}]'}]}}).encode()

    client = CohereSuggester(api_key="test-key", opener=lambda *a, **k: Response())
    result = client.generate_assistant_commands("clean files", ".", "linux", "bash")
    assert not result["ok"]
    assert result["commands"] == []
