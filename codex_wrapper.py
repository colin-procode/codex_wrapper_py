"""A small Python interface to the Codex CLI."""

from __future__ import annotations

import json
import argparse
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


DEFAULT_MODEL = "gpt-6-luna"


@dataclass(frozen=True)
class Message:
    role: str
    content: str


class CodexError(RuntimeError):
    """Raised when the Codex CLI fails or returns invalid output."""


class Codex:
    """Prompt Codex CLI, optionally restricting its tools to read-only access.

    Calls in one instance share a Codex thread. ``history`` exposes the user and
    assistant text exchanged through this instance for the lifetime of the object.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        read_only: bool = False,
        cwd: str | Path | None = None,
        executable: str = "codex",
        skip_git_repo_check: bool = False,
        thread_id: str | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("model must not be empty")
        self.model = model
        self.read_only = read_only
        self.cwd = Path(cwd).resolve() if cwd is not None else Path.cwd()
        self.executable = executable
        self.skip_git_repo_check = skip_git_repo_check
        self.thread_id = thread_id
        self._history: list[Message] = []

    @property
    def history(self) -> tuple[Message, ...]:
        """Messages exchanged via this wrapper instance, in chronological order."""
        return tuple(self._history)

    def prompt(self, message: str, images: Sequence[str | Path] = ()) -> str:
        """Send a prompt, optionally attaching images, and return final response text."""
        if not message.strip():
            raise ValueError("message must not be empty")
        if shutil.which(self.executable) is None and not Path(self.executable).is_file():
            raise FileNotFoundError(f"Codex executable not found: {self.executable}")

        command = [self.executable, "exec"]
        if self.thread_id:
            command.extend(["resume", self.thread_id])
        else:
            command.extend(["--cd", str(self.cwd)])
        if self.skip_git_repo_check:
            command.append("--skip-git-repo-check")
        for image in images:
            command.extend(["--image", str(Path(image).expanduser().resolve())])
        command.extend(["--json", "--model", self.model])
        if not self.thread_id:
            if self.read_only:
                command.extend(["--sandbox", "read-only"])
        command.append(message)

        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode:
            raise CodexError(
                f"Codex exited with status {result.returncode}: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        answer, thread_id = self._parse_events(result.stdout)
        self.thread_id = thread_id or self.thread_id
        self._history.extend((Message("user", message), Message("assistant", answer)))
        return answer

    def rename_thread(self, thread_id: str, name: str) -> None:
        """Rename a saved Codex thread using the Codex app-server protocol."""
        self._thread_operation("thread/name/set", {"threadId": thread_id, "name": name})

    def delete_thread(self, thread_id: str) -> None:
        """Delete a saved Codex thread using the Codex app-server protocol."""
        self._thread_operation("thread/delete", {"threadId": thread_id})

    def list_threads(self) -> list[dict[str, str]]:
        """List saved sessions with the metadata used by the task importer."""
        response = self._app_server_request("thread/list", {
            "limit": 100, "archived": False, "sortKey": "updated_at", "sortDirection": "desc",
            "sourceKinds": ["cli", "vscode", "exec", "appServer"],
        })
        sessions = []
        for thread in response.get("data", []):
            preview = str(thread.get("preview") or "")
            timestamp = thread.get("recencyAt") or thread.get("updatedAt") or thread.get("createdAt") or 0
            sessions.append({
                "sessionId": str(thread.get("id") or ""),
                "title": str(thread.get("name") or ((preview.splitlines() or [""])[0][:160]) or "Codex session")[:160],
                "preview": preview[:4_000],
                "workingDirectory": str(thread.get("cwd") or "")[:2048],
                "updatedAt": datetime.fromtimestamp(float(timestamp), timezone.utc).isoformat(),
            })
        return [session for session in sessions if session["sessionId"]]

    def read_thread(self, thread_id: str) -> dict[str, Any]:
        """Read a saved session and normalize its user and assistant messages."""
        response = self._app_server_request("thread/read", {"threadId": thread_id, "includeTurns": True})
        thread = response.get("thread", {})
        messages: list[dict[str, str]] = []
        turns = thread.get("turns", [])
        for turn in turns:
            started = turn.get("startedAt") or thread.get("createdAt") or 0
            completed = turn.get("completedAt") or started
            for item in turn.get("items", []):
                if item.get("type") == "userMessage":
                    text = "\n".join(part.get("text", "") for part in item.get("content", []) if part.get("type") == "text").strip()
                    if text:
                        messages.append({"role": "user", "text": text[:4_000], "createdAt": datetime.fromtimestamp(float(started), timezone.utc).isoformat()})
                elif item.get("type") == "agentMessage" and item.get("text", "").strip():
                    messages.append({"role": "assistant", "text": item["text"][:4_000], "createdAt": datetime.fromtimestamp(float(completed), timezone.utc).isoformat()})
        preview = str(thread.get("preview") or "")
        timestamp = thread.get("recencyAt") or thread.get("updatedAt") or thread.get("createdAt") or 0
        return {
            "sessionId": str(thread.get("id") or thread_id),
            "title": str(thread.get("name") or ((preview.splitlines() or [""])[0][:160]) or "Codex session")[:160],
            "preview": preview[:4_000],
            "workingDirectory": str(thread.get("cwd") or "")[:2048],
            "updatedAt": datetime.fromtimestamp(float(timestamp), timezone.utc).isoformat(),
            "messages": messages[-100:],
        }

    def _thread_operation(self, method: str, params: dict[str, str]) -> None:
        self._app_server_request(method, params)

    def _app_server_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if shutil.which(self.executable) is None and not Path(self.executable).is_file():
            raise FileNotFoundError(f"Codex executable not found: {self.executable}")
        process = subprocess.Popen(
            [self.executable, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )
        assert process.stdin is not None and process.stdout is not None
        try:
            process.stdin.write(json.dumps({"id": 1, "method": "initialize", "params": {
                "clientInfo": {"name": "codex_wrapper", "title": "Codex Wrapper", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True},
            }}) + "\n")
            process.stdin.flush()
            self._await_response(process.stdout, 1)
            process.stdin.write(json.dumps({"method": "initialized"}) + "\n")
            process.stdin.write(json.dumps({"id": 2, "method": method, "params": params}) + "\n")
            process.stdin.flush()
            response = self._await_response(process.stdout, 2)
            if "error" in response:
                raise CodexError(str(response["error"]))
            return response.get("result", {})
        finally:
            process.stdin.close()
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    @staticmethod
    def _await_response(stream: Any, request_id: int) -> dict[str, Any]:
        for line in stream:
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if response.get("id") == request_id:
                return response
        raise CodexError("Codex app-server exited before responding")

    @staticmethod
    def _parse_events(output: str) -> tuple[str, str | None]:
        thread_id: str | None = None
        final_text: str | None = None
        for line in output.splitlines():
            try:
                event: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = event.get("type")
            if kind == "thread.started":
                thread_id = event.get("thread_id")
            elif kind == "turn.completed":
                # `last_agent_message` is provided by current Codex CLI versions.
                final_text = event.get("last_agent_message", final_text)
            elif kind == "item.completed":
                item = event.get("item", {})
                if item.get("type") == "agent_message":
                    final_text = item.get("text", final_text)
        if final_text is None:
            raise CodexError("Codex returned no final assistant message")
        return final_text, thread_id


__all__: Sequence[str] = ("Codex", "CodexError", "Message", "DEFAULT_MODEL")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run and manage saved Codex sessions")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--codex", default=os.environ.get("CODEX_EXECUTABLE", "codex"))
    run.add_argument("--cwd", required=True)
    run.add_argument("--model", default=DEFAULT_MODEL)
    run.add_argument("--session-id")
    run.add_argument("--add-dir", action="append", default=[])
    run.add_argument("--skip-git-repo-check", action="store_true")
    rename = subparsers.add_parser("rename")
    rename.add_argument("--codex", default=os.environ.get("CODEX_EXECUTABLE", "codex"))
    rename.add_argument("session_id")
    rename.add_argument("name")
    delete = subparsers.add_parser("delete")
    delete.add_argument("--codex", default=os.environ.get("CODEX_EXECUTABLE", "codex"))
    delete.add_argument("session_id")
    list_sessions = subparsers.add_parser("list")
    list_sessions.add_argument("--codex", default=os.environ.get("CODEX_EXECUTABLE", "codex"))
    read = subparsers.add_parser("read")
    read.add_argument("--codex", default=os.environ.get("CODEX_EXECUTABLE", "codex"))
    read.add_argument("session_id")
    arguments = parser.parse_args()
    if arguments.operation == "run":
        command = [arguments.codex, "exec"]
        command.extend(["resume", arguments.session_id] if arguments.session_id else ["--cd", str(Path(arguments.cwd).resolve())])
        if not arguments.session_id:
            for directory in arguments.add_dir:
                command.extend(["--add-dir", str(Path(directory).resolve())])
        if arguments.skip_git_repo_check:
            command.append("--skip-git-repo-check")
        command.extend(["--json", "--model", arguments.model, "--dangerously-bypass-approvals-and-sandbox", "-"])
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert child.stdin is not None and child.stdout is not None and child.stderr is not None
        stderr_thread = threading.Thread(target=lambda: sys.stderr.buffer.write(child.stderr.read()), daemon=True)
        stderr_thread.start()
        child.stdin.write(sys.stdin.buffer.read())
        child.stdin.close()
        for line in iter(child.stdout.readline, b""):
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
        code = child.wait()
        stderr_thread.join()
        raise SystemExit(code)
    wrapper = Codex(executable=arguments.codex)
    try:
        if arguments.operation == "list":
            print(json.dumps({"sessions": wrapper.list_threads()}))
        elif arguments.operation == "read":
            print(json.dumps({"transcript": wrapper.read_thread(arguments.session_id)}))
        elif arguments.operation == "rename":
            wrapper.rename_thread(arguments.session_id, arguments.name)
        elif arguments.operation == "delete":
            wrapper.delete_thread(arguments.session_id)
    except (CodexError, FileNotFoundError) as error:
        parser.exit(1, f"codex_wrapper: {error}\n")


if __name__ == "__main__":
    main()
