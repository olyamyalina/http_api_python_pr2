import time
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from .models import Account, Base, Feedback, Message

MODELS = {"account": Account, "message": Message, "feedback": Feedback}
REPORT_WINDOW = 8 * 60


def enable_foreign_keys(connection, connection_record):
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{self.path.resolve().as_posix()}",
        )
        event.listen(self.engine, "connect", enable_foreign_keys)
        Base.metadata.create_all(self.engine)

    def collect(self, table, **filters):
        model = MODELS[table]
        statement = select(model).filter_by(**filters).order_by(model.uid)
        with Session(self.engine) as session:
            rows = session.scalars(statement).all()
            return [
                {
                    column.name: getattr(row, column.name)
                    for column in model.__table__.columns
                }
                for row in rows
            ]

    def inspect(self, table, uid):
        rows = self.collect(table, uid=uid)
        if not rows:
            raise ValueError("Record not found")
        return rows[0]

    def create(self, table, **fields):
        model = MODELS[table]
        with Session(self.engine) as session:
            row = model(timestamp=int(time.time()), **fields)
            session.add(row)
            session.commit()
            session.refresh(row)
            return {
                column.name: getattr(row, column.name)
                for column in model.__table__.columns
            }

    def modify(self, table, uid, fields):
        model = MODELS[table]
        with Session(self.engine) as session:
            row = session.get(model, uid)
            if not row:
                raise ValueError("Record not found")
            for key, value in fields.items():
                setattr(row, key, value)
            session.commit()
            return {
                column.name: getattr(row, column.name)
                for column in model.__table__.columns
            }

    def finish(self, uid, result, failure):
        with Session(self.engine) as session:
            with session.begin():
                message = session.get(Message, int(uid))
                if message is None:
                    raise ValueError("Record not found")
                feedback = Feedback(
                    timestamp=int(time.time()),
                    message=message.uid,
                    result=result,
                    failure=failure,
                    status="failed" if failure else "succeeded",
                )
                session.add(feedback)
                message.completed = 1

    def report(self):
        statement = (
            select(Account.ip, Message.argument)
            .outerjoin(Message, Account.uid == Message.account)
            .where(Account.timestamp >= time.time() - REPORT_WINDOW)
            .distinct()
        )
        with Session(self.engine) as session:
            rows = session.execute(statement).all()
            return [
                {"ip": row.ip, "argument": row.argument}
                for row in rows
            ]

    def close(self):
        self.engine.dispose()
