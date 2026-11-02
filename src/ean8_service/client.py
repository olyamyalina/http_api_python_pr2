"""API client with verb_table_action names and replaceable transport."""

import base64
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from .xmlio import serialize


class ApiClient:
    """Expose all eleven operations and return parsed XML elements."""

    def __init__(self, url, username, password, transport=None):
        """Configure the base URL, credentials and optional WSGI adapter."""
        self.url = url.rstrip("/")
        credentials = f"{username}:{password}".encode("utf-8")
        self.authorization = "Basic " + base64.b64encode(credentials).decode()
        self.transport = transport or self._http

    def _http(self, method, path, body, headers):
        """Perform a real HTTP request with a bounded connection timeout."""
        request = Request(self.url + path, body, headers, method=method)
        with urlopen(request, timeout=30) as reply:
            return reply.read()

    def _call(self, method, route, fields=None, xml=None):
        """Serialize request parameters and decode the XML response."""
        path = "/core/api/" + route
        if fields:
            path += "?" + urlencode(fields)
        headers = {"Authorization": self.authorization}
        body = None
        if xml is not None:
            body = serialize(xml, "record")
            headers["Content-Type"] = "application/xml; charset=utf-8"
        return ET.fromstring(self.transport(method, path, body, headers))

    def post_account_submit(self, ip):
        """Create an account with a validated IP address."""
        return self._call("POST", "account-submit", {"ip": ip})

    def get_account_collect(self, **filters):
        """Search accounts by IP and/or timestamp."""
        return self._call("GET", "account-collect", filters)

    def get_account_inspect(self, uid):
        """Read one account."""
        return self._call("GET", "account-inspect", {"uid": uid})

    def patch_account_modify(self, uid, **fields):
        """Modify account IP or timestamp using an XML body."""
        return self._call("PATCH", f"account-modify/{uid}", xml=fields)

    def post_message_submit(self, account, argument):
        """Submit a JSON argument string as query parameters."""
        return self._call("POST", "message-submit", {
            "account": account, "argument": argument,
        })

    def get_message_collect(self, account, **filters):
        """Search messages belonging to an account."""
        return self._call("GET", f"message-collect/{account}", filters)

    def get_message_inspect(self, uid):
        """Read one job and its completed flag."""
        return self._call("GET", "message-inspect", {"uid": uid})

    def patch_message_modify(self, uid, **fields):
        """Modify job account or timestamp using an XML body."""
        return self._call("PATCH", f"message-modify/{uid}", xml=fields)

    def get_feedback_collect(self, message, **filters):
        """Find results for one job, optionally filtered by status."""
        return self._call("GET", f"feedback-collect/{message}", filters)

    def get_feedback_inspect(self, uid):
        """Read a result: PDF Base64, status, and diagnostic failure."""
        return self._call("GET", "feedback-inspect", {"uid": uid})

    def get_report_collect(self):
        """Read the report defined by formula 15."""
        return self._call("GET", "report-collect")
