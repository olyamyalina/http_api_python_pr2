import base64
import json
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from http import HTTPStatus
from pathlib import Path
from xml.etree import ElementTree as ET

from hypothesis import settings, strategies as st
from hypothesis.stateful import (
    Bundle, RuleBasedStateMachine, initialize, invariant, rule,
    run_state_machine_as_test,
)
from webtest import TestApp

from ean8_service.api import create_app
from ean8_service.client import ApiClient
from ean8_service.storage import Store
from ean8_service.server import process_message

IPS = st.sampled_from(["127.0.0.1", "10.0.0.15", "::1"])
PAYLOADS = st.sampled_from(["1234567", "0000001", "96385074"])
UNIX_EPOCH = 0
FEEDBACK_PER_JOB = 1
REPORT_WINDOW_SECONDS = 480
OVERSIZED_BODY_BYTES = 65537
ROUTES = [
    ("POST", "account-submit"), ("GET", "account-collect"),
    ("GET", "account-inspect"), ("PATCH", "account-modify/1"),
    ("POST", "message-submit"), ("GET", "message-collect/1"),
    ("GET", "message-inspect"), ("PATCH", "message-modify/1"),
    ("GET", "feedback-collect/1"), ("GET", "feedback-inspect"),
    ("GET", "report-collect"),
]


BAD_CASES = {
    "missing_record": ("GET", "account-inspect?uid=99999", b""),
    "invalid_uid": ("GET", "account-inspect?uid=x", b""),
    "unknown_field": ("GET", "account-collect?unknown=1", b""),
    "missing_ip": ("POST", "account-submit", b""),
    "invalid_ip": ("POST", "account-submit?ip=invalid", b""),
    "empty_patch": ("PATCH", "account-modify/1", b"<record/>"),
    "malformed_xml": ("PATCH", "account-modify/1", b"broken"),
    "xml_declaration": ("PATCH", "account-modify/1", b"<!DOCTYPE x><x/>"),
    "duplicate_fields": ("PATCH", "account-modify/1", b"<x><ip/><ip/></x>"),
    "nested_xml": ("PATCH", "account-modify/1", b"<x><ip><x/></ip></x>"),
    "oversized_xml": ("PATCH", "account-modify/1", b""),
    "negative_timestamp": (
        "PATCH", "account-modify/1", b"<x><timestamp>-1</timestamp></x>",
    ),
    "invalid_json": (
        "POST", "message-submit?account=1&argument=invalid", b"",
    ),
    "missing_account": (
        "POST", "message-submit?account=99999&argument={}", b"",
    ),
}


def record(node):
    return {child.tag: child.text or "" for child in node}


def records(node):
    return [record(item) for item in node]


class AppModel(RuleBasedStateMachine):
    account_ids = Bundle("accounts")
    message_ids = Bundle("messages")

    def __init__(self):
        """Create an isolated database and independent reference model."""
        super().__init__()
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / "db.sqlite")
        self.accounts = {}
        self.messages = {}
        self.feedback = {}
        self.pool = ThreadPoolExecutor(max_workers=2)

    @initialize(test_mode=st.booleans())
    def start(self, test_mode):
        self.test_mode = test_mode
        process = partial(process_message, self.store, test_mode=test_mode)
        submit = partial(self.pool.submit, process)
        self.app = TestApp(create_app(self.store, submit, "user", "pass"))
        self.client = ApiClient("", "user", "pass", self.transport)

    def transport(self, method, path, body, headers):
        reply = self.app.request(
            path, method=method, body=body or b"", headers=headers,
        )
        assert reply.status_int == HTTPStatus.OK
        assert reply.content_type == "application/xml"
        return reply.body

    @rule(target=account_ids, ip=IPS)
    def create_account(self, ip):
        row = record(self.client.post_account_submit(ip))
        assert row["ip"] == ip
        assert int(row["timestamp"]) > UNIX_EPOCH
        assert row["uid"] not in self.accounts
        self.accounts[row["uid"]] = row
        return row["uid"]

    @rule(target=message_ids, account=account_ids, code=PAYLOADS)
    def create_message(self, account, code):
        argument = json.dumps({"codes": [code]})
        row = record(self.client.post_message_submit(account, argument))
        assert row["completed"] == "0"
        assert row["argument"] == argument
        assert row["account"] == account
        row["completed"] = "1"
        self.messages[row["uid"]] = row
        items = self.wait_feedback(row["uid"])
        assert len(items) == FEEDBACK_PER_JOB
        feedback = items[0]
        assert feedback["status"] == "succeeded"
        assert feedback["failure"] == ""
        if self.test_mode:
            assert feedback["result"] == ""
        else:
            assert base64.b64decode(feedback["result"]).startswith(b"%PDF-")
        self.feedback[feedback["uid"]] = feedback
        return row["uid"]

    def wait_feedback(self, message):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            items = records(self.client.get_feedback_collect(message))
            if items:
                return items
            time.sleep(0.01)
        raise AssertionError("No feedback before the deadline")

    @rule(account=account_ids, ip=IPS, old=st.booleans())
    def modify_account(self, account, ip, old):
        stamp = int(time.time()) - (600 if old else 0)
        expected = {
            **self.accounts[account], "ip": ip, "timestamp": str(stamp),
        }
        actual = record(self.client.patch_account_modify(
            account, ip=ip, timestamp=stamp,
        ))
        assert actual == expected
        self.accounts[account] = expected

    @rule(message=message_ids, account=account_ids, ownership=st.booleans())
    def modify_message(self, message, account, ownership):
        changes = {"timestamp": "1"}
        if ownership:
            changes["account"] = account
        expected = {**self.messages[message], **changes}
        actual = record(self.client.patch_message_modify(message, **changes))
        assert actual == expected
        self.messages[message] = expected

    @rule(route=st.sampled_from(ROUTES), header=st.sampled_from([
        "", "Basic !!!", "Bearer abc", "Basic dXNlcjpiYWQ=",
        "Basic /w==", "Basic bm9jb2xvbg==",
    ]))
    def unauthorized(self, route, header):
        method, path = route
        reply = self.app.request(
            "/core/api/" + path, method=method,
            headers={"Authorization": header}, expect_errors=True,
        )
        assert reply.status_int == HTTPStatus.UNAUTHORIZED
        assert reply.headers["WWW-Authenticate"].startswith("Basic ")
        assert ET.fromstring(reply.body).findtext("error") == "Unauthorized"

    @rule(case=st.sampled_from(tuple(BAD_CASES)))
    def invalid_request(self, case):
        method, path, body = BAD_CASES[case]
        if case == "oversized_xml":
            body = b"x" * OVERSIZED_BODY_BYTES
        reply = self.app.request(
            "/core/api/" + path, method=method, body=body,
            headers={"Authorization": self.client.authorization},
            expect_errors=True,
        )
        assert reply.status_int == HTTPStatus.BAD_REQUEST
        assert ET.fromstring(reply.body).findtext("error")

    @invariant()
    def matches_model(self):
        self.check_accounts()
        self.check_messages()
        for uid, expected in self.feedback.items():
            assert record(self.client.get_feedback_inspect(uid)) == expected
        self.check_report()
        reloaded = Store(self.store.path)
        try:
            assert reloaded.collect("account") == self.store.collect("account")
        finally:
            reloaded.close()

    def check_accounts(self):
        assert records(self.client.get_account_collect()) == list(
            self.accounts.values()
        )
        for uid, expected in self.accounts.items():
            assert record(self.client.get_account_inspect(uid)) == expected
            selected = records(self.client.get_account_collect(
                ip=expected["ip"],
            ))
            assert selected == [a for a in self.accounts.values()
                                if a["ip"] == expected["ip"]]
            messages = records(self.client.get_message_collect(
                uid, completed=1,
            ))
            assert messages == [m for m in self.messages.values()
                                if m["account"] == uid]

    def check_messages(self):
        for uid, expected in self.messages.items():
            assert record(self.client.get_message_inspect(uid)) == expected
            selected = records(self.client.get_feedback_collect(
                uid, status="succeeded",
            ))
            assert selected == [f for f in self.feedback.values()
                                if f["message"] == uid]

    def check_report(self):
        expected = set()
        for uid, account in self.accounts.items():
            if int(account["timestamp"]) >= time.time() - REPORT_WINDOW_SECONDS:
                arguments = {m["argument"] for m in self.messages.values()
                             if m["account"] == uid} or {""}
                expected.update((account["ip"], value) for value in arguments)
        actual = records(self.client.get_report_collect())
        assert {(row["ip"], row["argument"]) for row in actual} == expected
        assert len(actual) == len(expected)

    def teardown(self):
        try:
            self.pool.shutdown(wait=True)
        finally:
            try:
                self.store.close()
            finally:
                self.directory.cleanup()


def test_api_model():
    run_state_machine_as_test(
        AppModel,
        settings=settings(
            max_examples=40, stateful_step_count=30, deadline=None,
        ),
    )
