import argparse
import base64
import configparser
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

from bottle import run

from .api import create_app
from .storage import Store


def process_message(store, message, test_mode=False, timeout=30):
    """TODO: replace the simple background call with a dedicated worker."""
    try:
        result = "" if test_mode else convert(message["argument"], timeout)
        failure = ""
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result, failure = "", str(error)
    store.finish(message["uid"], result, failure)


def convert(argument, timeout):
    with tempfile.TemporaryDirectory(prefix="ean8-") as directory:
        source = Path(directory) / "input.json"
        source.write_text(argument, encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        process = subprocess.run(
            [sys.executable, "-m", "ean8_service.cli", str(source)],
            capture_output=True, timeout=timeout, env=env,
        )
    if process.returncode:
        raise ValueError(process.stderr.decode("utf-8", errors="replace"))
    if not process.stdout.startswith(b"%PDF-"):
        raise ValueError("CLI returned invalid PDF")
    return base64.b64encode(process.stdout).decode("ascii")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.ini")
    args = parser.parse_args()
    config = configparser.ConfigParser()
    if not config.read(args.config, encoding="utf-8"):
        parser.error("Configuration file not found; copy config.example.ini")
    options = config["server"]
    database = Path(args.config).resolve().parent / options["database"]
    store = Store(database)
    try:
        process = partial(
            process_message, store,
            test_mode=options.getboolean("test_mode"),
            timeout=options.getint("timeout"),
        )
        with ThreadPoolExecutor(
            max_workers=options.getint("workers"),
        ) as pool:
            submit = partial(pool.submit, process)
            app = create_app(
                store, submit, options["username"], options["password"],
            )
            for message in store.collect("message", completed=0):
                submit(message)
            run(app, host=options["host"], port=options.getint("port"))
    finally:
        store.close()


if __name__ == "__main__":
    main()
