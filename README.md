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

Each instance keeps its own in-memory message history and resumes its Codex
thread on subsequent prompts. History is not saved by this Python wrapper after
the process exits; Codex itself stores normal (non-ephemeral) CLI sessions.
Requires the `codex` executable to be installed and authenticated.
This project was documented and verified with **Codex CLI 0.163.0**. Check
the installed version with `codex --version`.

Run the wrapper tests with `python -m unittest -v`.
