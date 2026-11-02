"""Background queue that delegates PDF generation to the stage-one CLI."""

import base64
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


class Worker:
    """Run subprocesses without blocking HTTP handlers."""

    def __init__(self, store, test_mode=False, workers=2, timeout=30):
        """Create the executor with configurable process timeout."""
        self.store = store
        self.test_mode = test_mode
        self.timeout = timeout
        self.pool = ThreadPoolExecutor(max_workers=workers)

    def submit(self, message):
        """Queue a persisted message and return immediately."""
        self.pool.submit(self.execute, message)

    def execute(self, message):
        """Capture PDF stdout or diagnostic stderr as one feedback record."""
        try:
            result = "" if self.test_mode else self.convert(message["argument"])
            failure = ""
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            result, failure = "", str(error)
        self.store.finish(message["uid"], result, failure)

    def convert(self, argument):
        """Use an argument list, a temporary file and a finite timeout."""
        with tempfile.TemporaryDirectory(prefix="ean8-") as directory:
            source = Path(directory) / "input.json"
            source.write_text(argument, encoding="utf-8")
            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
            process = subprocess.run(
                [sys.executable, "-m", "ean8_service.cli", str(source)],
                capture_output=True, timeout=self.timeout, env=env,
            )
        if process.returncode:
            raise ValueError(process.stderr.decode("utf-8", errors="replace"))
        if not process.stdout.startswith(b"%PDF-"):
            raise ValueError("CLI returned invalid PDF")
        return base64.b64encode(process.stdout).decode("ascii")

    def close(self):
        """Drain queued work during graceful shutdown or test teardown."""
        self.pool.shutdown(wait=True)
