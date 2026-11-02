"""All HTTP handler coverage comes from Hypothesis state-machine tests."""

import base64
import json
import tempfile
import time
from http import HTTPStatus
from pathlib import Path
from xml.etree import ElementTree as ET

from hypothesis import settings, strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine, initialize, invariant, rule,
)
from webtest import TestApp

from ean8_service.api import create_app
from ean8_service.client import ApiClient
from ean8_service.storage import Store
from ean8_service.worker import Worker

IPS = st.sampled_from(["127.0.0.1", "10.0.0.15", "::1"])
PAYLOADS = st.sampled_from(["1234567", "0000001", "96385074"])
UNIX_EPOCH = 0
FEEDBACK_PER_JOB = 1
REPORT_WINDOW_SECONDS = 480
ROUTES = [
    ("POST", "account-submit"), ("GET", "account-collect"),
    ("GET", "account-inspect"), ("PATCH", "account-modify/1"),
    ("POST", "message-submit"), ("GET", "message-collect/1"),
    ("GET", "message-inspect"), ("PATCH", "message-modify/1"),
    ("GET", "feedback-collect/1"), ("GET", "feedback-inspect"),
    ("GET", "report-collect"),
]


BAD_CASES = [
    ("GET", "account-inspect?uid=99999", b""),
    ("GET", "account-inspect?uid=x", b""),
    ("GET", "account-collect?unknown=1", b""),
    ("POST", "account-submit", b""),
    ("POST", "account-submit?ip=invalid", b""),
    ("PATCH", "account-modify/1", b"<record/>"),
    ("PATCH", "account-modify/1", b"broken"),
    ("PATCH", "account-modify/1", b"<!DOCTYPE x><x/>"),
    ("PATCH", "account-modify/1", b"<x><ip/><ip/></x>"),
    ("PATCH", "account-modify/1", b"<x><ip><x/></ip></x>"),
    ("PATCH", "account-modify/1", b"x" * 65537),
    ("PATCH", "account-modify/1", b"<x><timestamp>-1</timestamp></x>"),
    ("POST", "message-submit?account=1&argument=invalid", b""),
    ("POST", "message-submit?account=99999&argument={}", b""),
]


def record(node):
    """Convert XML into a plain reference-model record."""
    return {child.tag: child.text or "" for child in node}


def records(node):
    """Convert a collection response into reference-model records."""
    return [record(item) for item in node]


class ApiMachine(RuleBasedStateMachine):
    """Generate submissions, updates, reads, filtering and invalid calls."""

    def __init__(self):
        """Create an isolated database and independent reference model."""
        super().__init__()
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / "db.json")
        self.accounts = {}
        self.messages = {}
        self.feedback = {}

    @initialize(test_mode=st.booleans(),
                bad_cases=st.permutations(BAD_CASES),
                denied=st.permutations(ROUTES),
                ownership=st.permutations([False, True]))
    def start(self, test_mode, bad_cases, denied, ownership):
        """Generate initial state and mandatory request permutations."""
        self.test_mode = test_mode
        self.worker = Worker(self.store, test_mode=test_mode)
        self.app = TestApp(create_app(self.store, self.worker, "user", "pass"))
        self.client = ApiClient("", "user", "pass", self.transport)
        self.add_account("127.0.0.1")
        self.add_message("1234567", 0)
        self.modify_account("::1", False, 0)
        for change_owner in ownership:
            self.modify_message(0, change_owner)
        for case in bad_cases:
            self.invalid_request(case)
        for route in denied:
            self.unauthorized(route, "")

    def transport(self, method, path, body, headers):
        """Drive the real Bottle WSGI application through ApiClient."""
        reply = self.app.request(
            path, method=method, body=body or b"", headers=headers,
        )
        assert reply.status_int == HTTPStatus.OK
        assert reply.content_type == "application/xml"
        return reply.body

    @rule(ip=IPS)
    def add_account(self, ip):
        """Create an account and extend the reference model."""
        row = record(self.client.post_account_submit(ip))
        assert row["ip"] == ip
        assert int(row["timestamp"]) > UNIX_EPOCH
        assert row["uid"] not in self.accounts
        self.accounts[row["uid"]] = row

    @rule(code=PAYLOADS, index=st.integers(min_value=0, max_value=30))
    def add_message(self, code, index):
        """Submit a job and compare its terminal state with the model."""
        account = list(self.accounts)[index % len(self.accounts)]
        argument = json.dumps({"codes": [code]})
        row = record(self.client.post_message_submit(account, argument))
        assert row["completed"] == "0"
        assert row["argument"] == argument
        assert row["account"] == account
        self.worker.pool.submit(lambda: None).result(timeout=15)
        self.worker.close()
        row["completed"] = "1"
        self.messages[row["uid"]] = row
        items = records(self.client.get_feedback_collect(row["uid"]))
        assert len(items) == FEEDBACK_PER_JOB
        feedback = items[0]
        assert feedback["status"] == "succeeded"
        assert feedback["failure"] == ""
        if self.test_mode:
            assert feedback["result"] == ""
        else:
            assert base64.b64decode(feedback["result"]).startswith(b"%PDF-")
        self.feedback[feedback["uid"]] = feedback
        self.worker = Worker(self.store, test_mode=self.test_mode)
        self.app = TestApp(create_app(self.store, self.worker, "user", "pass"))

    @rule(ip=IPS, old=st.booleans(), index=st.integers(0, 30))
    def modify_account(self, ip, old, index):
        """Generate changes crossing the report time-window boundary."""
        uid = list(self.accounts)[index % len(self.accounts)]
        stamp = int(time.time()) - (600 if old else 0)
        expected = {**self.accounts[uid], "ip": ip, "timestamp": str(stamp)}
        actual = record(self.client.patch_account_modify(
            uid, ip=ip, timestamp=stamp,
        ))
        assert actual == expected
        self.accounts[uid] = expected

    @rule(index=st.integers(0, 30), ownership=st.booleans())
    def modify_message(self, index, ownership):
        """Generate ownership and timestamp updates."""
        uid = list(self.messages)[index % len(self.messages)]
        account = list(self.accounts)[index % len(self.accounts)]
        changes = {"timestamp": "1"}
        if ownership:
            changes["account"] = account
        expected = {**self.messages[uid], **changes}
        actual = record(self.client.patch_message_modify(uid, **changes))
        assert actual == expected
        self.messages[uid] = expected

    @rule(route=st.sampled_from(ROUTES), header=st.sampled_from([
        "", "Basic !!!", "Bearer abc", "Basic dXNlcjpiYWQ=",
        "Basic /w==", "Basic bm9jb2xvbg==",
    ]))
    def unauthorized(self, route, header):
        """Reject generated unauthorized calls before parameter parsing."""
        method, path = route
        reply = self.app.request(
            "/core/api/" + path, method=method,
            headers={"Authorization": header}, expect_errors=True,
        )
        assert reply.status_int == HTTPStatus.UNAUTHORIZED
        assert reply.headers["WWW-Authenticate"].startswith("Basic ")
        assert ET.fromstring(reply.body).findtext("error") == "Unauthorized"

    @rule(case=st.sampled_from(BAD_CASES))
    def invalid_request(self, case):
        """Compare a generated malformed request with the error model."""
        method, path, body = case
        reply = self.app.request(
            "/core/api/" + path, method=method, body=body,
            headers={"Authorization": self.client.authorization},
            expect_errors=True,
        )
        assert reply.status_int == HTTPStatus.BAD_REQUEST
        assert ET.fromstring(reply.body).findtext("error")

    @invariant()
    def matches_model(self):
        """Check all visible records after every generated transition."""
        self.check_accounts()
        self.check_messages()
        for uid, expected in self.feedback.items():
            assert record(self.client.get_feedback_inspect(uid)) == expected
        self.check_report()
        reloaded = Store(self.store.path)
        assert reloaded.collect("account") == self.store.collect("account")

    def check_accounts(self):
        """Compare account reads, filters and associated jobs with the model."""
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
        """Compare message reads and associated feedback with the model."""
        for uid, expected in self.messages.items():
            assert record(self.client.get_message_inspect(uid)) == expected
            selected = records(self.client.get_feedback_collect(
                uid, status="succeeded",
            ))
            assert selected == [f for f in self.feedback.values()
                                if f["message"] == uid]

    def check_report(self):
        """Independent set model including accounts without messages."""
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
        """Drain background work and remove the isolated database."""
        self.worker.close()
        self.directory.cleanup()


TestApi = ApiMachine.TestCase
TestApi.settings = settings(max_examples=20, stateful_step_count=20,
                            deadline=None)
