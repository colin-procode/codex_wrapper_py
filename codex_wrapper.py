"""A small Python interface to the Codex CLI."""

from __future__ import annotations

import json
import shutil
import subprocess
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
    ) -> None:
        if not model.strip():
            raise ValueError("model must not be empty")
        self.model = model
        self.read_only = read_only
        self.cwd = Path(cwd).resolve() if cwd is not None else Path.cwd()
        self.executable = executable
        self.skip_git_repo_check = skip_git_repo_check
        self.thread_id: str | None = None
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
