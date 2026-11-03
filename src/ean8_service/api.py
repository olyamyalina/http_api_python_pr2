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
MIN_INTEGER_VALUE = 0


def authorized(username, password):
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
    def decorate(handler):
        @functools.wraps(handler)
        def wrapped(*args, **kwargs):
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
    fields = dict(request.query)
    return checked(fields, allowed, required)


def checked(fields, allowed, required=()):
    if set(fields) - set(allowed) or set(required) - set(fields):
        raise ValueError("Unknown or missing fields")
    for key in fields.keys() & INTEGER_FIELDS:
        fields[key] = int(fields[key])
        if fields[key] < MIN_INTEGER_VALUE:
            raise ValueError("Integer fields must be nonnegative")
    if "ip" in fields:
        ipaddress.ip_address(fields["ip"])
    return fields


def patch_fields(allowed):
    body = request.body.read(MAX_BODY + 1)
    if len(body) > MAX_BODY:
        raise ValueError("XML body is too large")
    fields = checked(parse(body), allowed)
    if not fields:
        raise ValueError("Empty patch")
    return fields


def create_app(store, worker, username, password):
    app = Bottle()
    app.install(protect(username, password))
    register_accounts(app, store)
    register_messages(app, store, worker)
    register_feedback(app, store)

    @app.get("/core/api/report-collect")
    def get_report_collect():
        return store.report()

    return app


def register_accounts(app, store):
    @app.post("/core/api/account-submit")
    def post_account_submit():
        fields = query_fields({"ip"}, {"ip"})
        return store.create("account", **fields)

    @app.get("/core/api/account-collect")
    def get_account_collect():
        return store.collect("account", **query_fields({"ip", "timestamp"}))

    @app.get("/core/api/account-inspect")
    def get_account_inspect():
        return store.inspect("account", **query_fields({"uid"}, {"uid"}))

    @app.patch("/core/api/account-modify/<uid:int>")
    def patch_account_modify(uid):
        return store.modify("account", uid, patch_fields({"ip", "timestamp"}))


def register_messages(app, store, worker):
    @app.post("/core/api/message-submit")
    def post_message_submit():
        fields = query_fields({"account", "argument"}, {"account", "argument"})
        store.inspect("account", fields["account"])
        validate(json.loads(fields["argument"]))
        message = store.create("message", completed=0, **fields)
        worker.submit(message)
        return message

    @app.get("/core/api/message-collect/<account:int>")
    def get_message_collect(account):
        fields = query_fields({"completed", "timestamp", "argument"})
        return store.collect("message", account=account, **fields)

    @app.get("/core/api/message-inspect")
    def get_message_inspect():
        return store.inspect("message", **query_fields({"uid"}, {"uid"}))

    @app.patch("/core/api/message-modify/<uid:int>")
    def patch_message_modify(uid):
        fields = patch_fields({"account", "timestamp"})
        if "account" in fields:
            store.inspect("account", fields["account"])
        return store.modify("message", uid, fields)


def register_feedback(app, store):
    @app.get("/core/api/feedback-collect/<message:int>")
    def get_feedback_collect(message):
        fields = query_fields({"status", "timestamp"})
        return store.collect("feedback", message=message, **fields)

    @app.get("/core/api/feedback-inspect")
    def get_feedback_inspect():
        return store.inspect("feedback", **query_fields({"uid"}, {"uid"}))
