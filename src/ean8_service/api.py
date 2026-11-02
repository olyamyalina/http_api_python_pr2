"""Variant 15: eleven Bottle routes, XML responses and RFC 7617 auth."""

import base64
import binascii
import functools
import hmac
import ipaddress
import json

from bottle import Bottle, request, response

from .barcode import validate
from .xmlio import parse, serialize

INTEGER_FIELDS = {"timestamp", "account", "completed", "uid", "message"}
MAX_BODY = 65536


def authorized(username, password):
    """Check a UTF-8 Basic credential pair without logging secrets."""
    try:
        scheme, value = request.headers.get("Authorization", "").split()
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
        user, secret = decoded.split(":", 1)
        return (scheme.lower() == "basic"
                and hmac.compare_digest(user.encode(), username.encode())
                and hmac.compare_digest(secret.encode(), password.encode()))
    except (ValueError, UnicodeError, binascii.Error):
        return False


def protect(username, password):
    """Wrap every route with authentication and uniform XML errors."""
    def decorate(handler):
        """Attach the authentication and error-response wrapper."""
        @functools.wraps(handler)
        def wrapped(*args, **kwargs):
            """Return a serialized result or a serialized client error."""
            response.content_type = "application/xml; charset=UTF-8"
            if not authorized(username, password):
                response.status = 401
                response.set_header(
                    "WWW-Authenticate", 'Basic realm="ean8", charset="UTF-8"',
                )
                return serialize({"error": "Unauthorized"})
            try:
                return serialize(handler(*args, **kwargs))
            except (ValueError, KeyError) as error:
                response.status = 400
                return serialize({"error": str(error)})
        return wrapped
    return decorate


def query_fields(allowed, required=()):
    """Read and type-check query fields, rejecting unknown names."""
    fields = dict(request.query)
    return checked(fields, allowed, required)


def checked(fields, allowed, required=()):
    """Validate the explicitly supported mutable fields."""
    if set(fields) - set(allowed) or set(required) - set(fields):
        raise ValueError("Unknown or missing fields")
    for key in fields.keys() & INTEGER_FIELDS:
        fields[key] = int(fields[key])
        if fields[key] < 0:
            raise ValueError("Integer fields must be nonnegative")
    if "ip" in fields:
        ipaddress.ip_address(fields["ip"])
    return fields


def patch_fields(allowed):
    """Read a bounded XML PATCH body."""
    body = request.body.read(MAX_BODY + 1)
    if len(body) > MAX_BODY:
        raise ValueError("XML body is too large")
    fields = checked(parse(body), allowed)
    if not fields:
        raise ValueError("Empty patch")
    return fields


def create_app(store, worker, username, password):
    """Build an isolated application with injectable storage and worker."""
    app = Bottle()
    app.install(protect(username, password))
    register_accounts(app, store)
    register_messages(app, store, worker)
    register_feedback(app, store)

    @app.get("/core/api/report-collect")
    def get_report_collect():
        """Return distinct IP/argument pairs for recent accounts."""
        return store.report()

    return app


def register_accounts(app, store):
    """Register all four Account operations."""
    @app.post("/core/api/account-submit")
    def post_account_submit():
        """Create an account using query-string parameters."""
        fields = query_fields({"ip"}, {"ip"})
        return store.create("account", **fields)

    @app.get("/core/api/account-collect")
    def get_account_collect():
        """Search accounts using exact-match filters."""
        return store.collect("account", **query_fields({"ip", "timestamp"}))

    @app.get("/core/api/account-inspect")
    def get_account_inspect():
        """Read an account identified by query-string uid."""
        return store.inspect("account", **query_fields({"uid"}, {"uid"}))

    @app.patch("/core/api/account-modify/<uid:int>")
    def patch_account_modify(uid):
        """Update mutable account fields from XML."""
        return store.modify("account", uid, patch_fields({"ip", "timestamp"}))


def register_messages(app, store, worker):
    """Register immutable job submissions and mutable ownership metadata."""
    @app.post("/core/api/message-submit")
    def post_message_submit():
        """Validate, persist and asynchronously enqueue a generation job."""
        fields = query_fields({"account", "argument"}, {"account", "argument"})
        store.inspect("account", fields["account"])
        validate(json.loads(fields["argument"]))
        message = store.create("message", completed=0, **fields)
        worker.submit(message)
        return message

    @app.get("/core/api/message-collect/<account:int>")
    def get_message_collect(account):
        """Search jobs belonging to the account in the path."""
        fields = query_fields({"completed", "timestamp", "argument"})
        return store.collect("message", account=account, **fields)

    @app.get("/core/api/message-inspect")
    def get_message_inspect():
        """Read a job identified by query-string uid."""
        return store.inspect("message", **query_fields({"uid"}, {"uid"}))

    @app.patch("/core/api/message-modify/<uid:int>")
    def patch_message_modify(uid):
        """Change ownership or timestamp while preserving job input."""
        fields = patch_fields({"account", "timestamp"})
        if "account" in fields:
            store.inspect("account", fields["account"])
        return store.modify("message", uid, fields)


def register_feedback(app, store):
    """Expose generated results through the two read-only endpoints."""
    @app.get("/core/api/feedback-collect/<message:int>")
    def get_feedback_collect(message):
        """Search results associated with the job in the path."""
        fields = query_fields({"status", "timestamp"})
        return store.collect("feedback", message=message, **fields)

    @app.get("/core/api/feedback-inspect")
    def get_feedback_inspect():
        """Read one terminal execution result."""
        return store.inspect("feedback", **query_fields({"uid"}, {"uid"}))
