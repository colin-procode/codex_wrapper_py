Utilize OpenAI API features using just your monthly subscription with codex wrapper

# Codex Wrapper Py

A small, dependency-free wrapper for prompting the installed Codex CLI.

```python
from codex_wrapper import Codex

codex = Codex()  # defaults to gpt-6-luna
answer = codex.prompt("Summarize the files in this project")
print(answer)
print(codex.history)  # chronological Message(role, content) objects
```

Use `Codex(read_only=True)` to start the session with Codex's `read-only`
sandbox, or pass a model and working directory:

```python
codex = Codex(model="gpt-6-luna", read_only=True, cwd=".")
```

Resume a session by passing its saved thread ID:

```python
codex = Codex(thread_id="01a181f3-18e9-7872-857f-c7710adb0e90")
answer = codex.prompt("Continue the task")
```

The worker uses the wrapper's streaming runner so JSONL events remain available
to task activity, and uses its app-server helpers to rename or delete linked
threads. `CODEX_WRAPPER_PATH` can point the worker to `codex_wrapper.py` when
the wrapper is not at `../codex_wrapper/codex_wrapper.py` relative to the
Agent Manager checkout.

For a workspace that is not inside a Git repository, pass
`skip_git_repo_check=True` to allow Codex CLI to use that directory.

Each instance keeps its own in-memory message history and resumes its Codex
thread on subsequent prompts. History is not saved by this Python wrapper after
the process exits; Codex itself stores normal (non-ephemeral) CLI sessions.
Requires the `codex` executable to be installed and authenticated.

Attach local image references to a prompt with `images`:

```python
answer = codex.prompt("Describe these characters", images=["refs/character.png"])
```
This project was documented and verified with **Codex CLI 0.163.0**. Check
the installed version with `codex --version`.

Run the wrapper tests with `python -m unittest -v`.
