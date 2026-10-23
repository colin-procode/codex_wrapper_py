import json
import unittest
from unittest.mock import patch

from codex_wrapper import Codex, CodexError, DEFAULT_MODEL


def events(text, thread="thread-123"):
    return "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": thread}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": text}}),
            json.dumps({"type": "turn.completed", "last_agent_message": text}),
        ]
    )


class CodexWrapperTests(unittest.TestCase):
    @patch("codex_wrapper.subprocess.run")
    @patch("codex_wrapper.shutil.which", return_value="/usr/bin/codex")
    def test_defaults_to_luna_and_sets_read_only_sandbox(self, _which, run):
        run.return_value.returncode = 0
        run.return_value.stdout = events("hello")
        run.return_value.stderr = ""
        client = Codex(read_only=True)

        self.assertEqual(client.model, DEFAULT_MODEL)
        self.assertEqual(client.prompt("Say hello"), "hello")
        args = run.call_args.args[0]
        self.assertEqual(args[args.index("--model") + 1], "gpt-6-luna")
        self.assertEqual(args[args.index("--sandbox") + 1], "read-only")
        self.assertEqual(client.thread_id, "thread-123")
        self.assertEqual([m.role for m in client.history], ["user", "assistant"])

    @patch("codex_wrapper.subprocess.run")
    @patch("codex_wrapper.shutil.which", return_value="/usr/bin/codex")
    def test_follow_up_resumes_thread_and_appends_history(self, _which, run):
        run.return_value.returncode = 0
        run.return_value.stdout = events("first")
        run.return_value.stderr = ""
        client = Codex(model="gpt-6.1-sol")
        client.prompt("first question")
        run.return_value.stdout = events("second", thread="thread-123")
        self.assertEqual(client.prompt("follow up"), "second")
        args = run.call_args.args[0]
        self.assertEqual(args[2:5], ["resume", "thread-123", "--json"])
        self.assertIn("--model", args)
        self.assertEqual(len(client.history), 4)

    @patch("codex_wrapper.subprocess.run")
    @patch("codex_wrapper.shutil.which", return_value="/usr/bin/codex")
    def test_can_skip_git_repo_check(self, _which, run):
        run.return_value.returncode = 0
        run.return_value.stdout = events("hello")
        run.return_value.stderr = ""
        client = Codex(skip_git_repo_check=True)

        self.assertEqual(client.prompt("Say hello"), "hello")
        self.assertIn("--skip-git-repo-check", run.call_args.args[0])

    @patch("codex_wrapper.subprocess.run")
    @patch("codex_wrapper.shutil.which", return_value="/usr/bin/codex")
    def test_attaches_images_to_prompt(self, _which, run):
        run.return_value.returncode = 0
        run.return_value.stdout = events("hello")
        run.return_value.stderr = ""
        client = Codex()

        client.prompt("Describe this character", images=["character.png"])
        args = run.call_args.args[0]
        self.assertIn("--image", args)
        self.assertEqual(args[args.index("--image") + 1], str(__import__("pathlib").Path("character.png").resolve()))

    @patch("codex_wrapper.subprocess.run")
    @patch("codex_wrapper.shutil.which", return_value="/usr/bin/codex")
    def test_cli_error_does_not_add_history(self, _which, run):
        run.return_value.returncode = 2
        run.return_value.stdout = ""
        run.return_value.stderr = "bad invocation"
        client = Codex()
        with self.assertRaisesRegex(CodexError, "bad invocation"):
            client.prompt("hello")
        self.assertEqual(client.history, ())

    def test_rejects_blank_prompt(self):
        with self.assertRaises(ValueError):
            Codex().prompt("   ")


if __name__ == "__main__":
    unittest.main()
