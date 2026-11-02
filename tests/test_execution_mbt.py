"""Hypothesis-generated checks for pending jobs and CLI failure feedback."""

import base64
import json
import subprocess
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from hypothesis import settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule
from webtest import TestApp

from ean8_service.api import create_app
from ean8_service.client import ApiClient
from ean8_service.storage import Store
from ean8_service.worker import Worker

FEEDBACK_PER_JOB = 1


class ExecutionMachine(RuleBasedStateMachine):
    """Observe a blocked subprocess and its eventual terminal state."""

    @rule(outcome=st.sampled_from(["pdf", "exit", "invalid", "timeout", "os"]))
    def execute_job(self, outcome):
        """Generate and inspect a complete asynchronous job lifecycle."""
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "db.json")
            worker = Worker(store)
            app = TestApp(create_app(store, worker, "u", "p"))
            client = ApiClient("", "u", "p", self.transport(app))
            account = client.post_account_submit("::1").findtext("uid")
            started, release = threading.Event(), threading.Event()
            fake_run = self.fake_process(outcome, started, release)
            try:
                with patch("ean8_service.worker.subprocess.run", fake_run):
                    job = client.post_message_submit(
                        account, json.dumps({"codes": ["1234567"]}),
                    ).findtext("uid")
                    assert started.wait(timeout=5)
                    pending = client.get_message_inspect(job)
                    assert pending.findtext("completed") == "0"
                    assert not len(client.get_feedback_collect(job))
                    release.set()
                    worker.close()
                self.check_result(client, job, outcome)
            finally:
                release.set()
                worker.close()

    @staticmethod
    def transport(app):
        """Adapt WebTest without bypassing ApiClient serialization."""
        def send(method, path, body, headers):
            """Send one client request to the Bottle WSGI application."""
            return app.request(path, method=method, body=body or b"",
                               headers=headers).body
        return send

    @staticmethod
    def fake_process(outcome, started, release):
        """Hold the child process so the pending state can be inspected."""
        def run(command, **kwargs):
            """Return a generated subprocess outcome after release."""
            module_arguments = command[1:3]
            assert module_arguments == ["-m", "ean8_service.cli"]
            assert Path(command[3]).exists()
            started.set()
            assert release.wait(timeout=5)
            if outcome == "timeout":
                raise subprocess.TimeoutExpired(command, 30)
            if outcome == "os":
                raise OSError("child unavailable")
            code = 2 if outcome == "exit" else 0
            stdout = b"%PDF-test" if outcome == "pdf" else b"not pdf"
            return subprocess.CompletedProcess(command, code, stdout, b"error")
        return run

    @staticmethod
    def check_result(client, job, outcome):
        """Match job and feedback state against the generated outcome."""
        assert client.get_message_inspect(job).findtext("completed") == "1"
        items = client.get_feedback_collect(job)
        assert len(items) == FEEDBACK_PER_JOB
        result = items[0]
        if outcome == "pdf":
            assert result.findtext("status") == "succeeded"
            assert base64.b64decode(result.findtext("result")) == b"%PDF-test"
        else:
            assert result.findtext("status") == "failed"
            assert result.findtext("failure")
            assert not result.findtext("result")


TestExecution = ExecutionMachine.TestCase
TestExecution.settings = settings(max_examples=10, stateful_step_count=8,
                                  deadline=None)
