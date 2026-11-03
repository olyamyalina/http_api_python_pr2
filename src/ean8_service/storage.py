import copy
import json
import threading
import time
from pathlib import Path

TABLES = ("account", "message", "feedback")
REPORT_WINDOW = 8 * 60


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.data = {table: [] for table in TABLES}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data), encoding="utf-8")
        temporary.replace(self.path)

    def collect(self, table, **filters):
        with self.lock:
            return copy.deepcopy([
                row for row in self.data[table]
                if all(str(row.get(k)) == str(v) for k, v in filters.items())
            ])

    def inspect(self, table, uid):
        rows = self.collect(table, uid=uid)
        if not rows:
            raise ValueError("Record not found")
        return rows[0]

    def create(self, table, **fields):
        with self.lock:
            uid = max((r["uid"] for r in self.data[table]), default=0) + 1
            row = {"uid": uid, "timestamp": int(time.time()), **fields}
            self.data[table].append(row)
            self._save()
            return copy.deepcopy(row)

    def modify(self, table, uid, fields):
        with self.lock:
            self.inspect(table, uid)
            row = next(r for r in self.data[table] if r["uid"] == int(uid))
            row.update(fields)
            self._save()
            return copy.deepcopy(row)

    def finish(self, uid, result, failure):
        with self.lock:
            message = next(r for r in self.data["message"] if r["uid"] == uid)
            feedback_uid = len(self.data["feedback"]) + 1
            self.data["feedback"].append({
                "uid": feedback_uid, "timestamp": int(time.time()),
                "message": uid, "result": result, "failure": failure,
                "status": "failed" if failure else "succeeded",
            })
            message["completed"] = 1
            self._save()

    def report(self):
        with self.lock:
            rows = set()
            for account in self.data["account"]:
                if account["timestamp"] >= time.time() - REPORT_WINDOW:
                    messages = self.collect("message", account=account["uid"])
                    for message in messages or [{"argument": None}]:
                        rows.add((account["ip"], message["argument"]))
            return [{"ip": ip, "argument": argument}
                    for ip, argument in sorted(rows, key=repr)]
