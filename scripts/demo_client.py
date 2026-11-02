"""Submit one real HTTP job, poll feedback and save the PDF."""

import argparse
import base64
import configparser
import json
import time
from pathlib import Path

from ean8_service.client import ApiClient


def wait_result(client, message, timeout=60):
    """Poll a job with a deadline and return successful PDF bytes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        feedback = client.get_feedback_collect(message)
        if len(feedback):
            item = feedback[0]
            if item.findtext("status") != "succeeded":
                raise RuntimeError(item.findtext("failure"))
            result = base64.b64decode(item.findtext("result") or "")
            if not result.startswith(b"%PDF-"):
                raise RuntimeError("No PDF: disable test_mode in config")
            return result
        time.sleep(0.1)
    raise TimeoutError("The generation task did not finish")


def main():
    """Use credentials from the same configuration as the server."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.ini")
    args = parser.parse_args()
    config = configparser.ConfigParser()
    config.read(args.config, encoding="utf-8")
    options = config["server"]
    client = ApiClient(
        f"http://{options['host']}:{options['port']}",
        options["username"], options["password"],
    )
    account = client.post_account_submit("127.0.0.1").findtext("uid")
    message = client.post_message_submit(
        account, json.dumps({"codes": ["1234567", "96385074"]}),
    ).findtext("uid")
    result = wait_result(client, message)
    output = Path("output/pdf/api-result.pdf")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(result)
    print(f"Message {message}: {output} ({len(result)} bytes)")


if __name__ == "__main__":
    main()
