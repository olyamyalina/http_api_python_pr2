import base64
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree.ElementTree import fromstring

from .xmlio import serialize


class ApiClient:

    def __init__(self, url, username, password, transport=None):
        self.url = url.rstrip("/")
        credentials = f"{username}:{password}".encode("utf-8")
        self.authorization = "Basic " + base64.b64encode(credentials).decode()
        self.transport = transport or self._http

    def _http(self, method, path, body, headers):
        request = Request(self.url + path, body, headers, method=method)
        with urlopen(request, timeout=30) as reply:
            return reply.read()

    def _call(self, method, route, fields=None, xml=None):
        path = "/core/api/" + route
        if fields:
            path += "?" + urlencode(fields)
        headers = {"Authorization": self.authorization}
        body = None
        if xml is not None:
            body = serialize(xml, "record")
            headers["Content-Type"] = "application/xml; charset=utf-8"
        return fromstring(self.transport(method, path, body, headers))

    def post_account_submit(self, ip):
        return self._call("POST", "account-submit", {"ip": ip})

    def get_account_collect(self, **filters):
        return self._call("GET", "account-collect", filters)

    def get_account_inspect(self, uid):
        """Read one account."""
        return self._call("GET", "account-inspect", {"uid": uid})

    def patch_account_modify(self, uid, **fields):
        return self._call("PATCH", f"account-modify/{uid}", xml=fields)

    def post_message_submit(self, account, argument):
        return self._call("POST", "message-submit", {
            "account": account, "argument": argument,
        })

    def get_message_collect(self, account, **filters):
        return self._call("GET", f"message-collect/{account}", filters)

    def get_message_inspect(self, uid):
        return self._call("GET", "message-inspect", {"uid": uid})

    def patch_message_modify(self, uid, **fields):
        return self._call("PATCH", f"message-modify/{uid}", xml=fields)

    def get_feedback_collect(self, message, **filters):
        return self._call("GET", f"feedback-collect/{message}", filters)

    def get_feedback_inspect(self, uid):
        return self._call("GET", "feedback-inspect", {"uid": uid})

    def get_report_collect(self):
        return self._call("GET", "report-collect")
