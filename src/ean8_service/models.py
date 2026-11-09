from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import ForeignKey


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "account"

    uid: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[int] = mapped_column()
    ip: Mapped[str] = mapped_column()


class Message(Base):
    __tablename__ = "message"

    uid: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[int] = mapped_column()
    argument: Mapped[str] = mapped_column()
    account: Mapped[int] = mapped_column(ForeignKey("account.uid"))
    completed: Mapped[int] = mapped_column(default=0)


class Feedback(Base):
    __tablename__ = "feedback"

    uid: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[int] = mapped_column()
    result: Mapped[str] = mapped_column()
    status: Mapped[str] = mapped_column()
    failure: Mapped[str] = mapped_column()
    message: Mapped[int] = mapped_column(ForeignKey("message.uid"))
