from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class InboundEmail(Base):
    __tablename__ = "inbound_emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    sender_email: Mapped[str] = mapped_column(String(255), index=True)
    subject: Mapped[str] = mapped_column(String(500), default="")
    body_text: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    draft: Mapped["QuoteDraft | None"] = relationship(back_populates="inbound_email", uselist=False)


class QuoteDraft(Base):
    __tablename__ = "quote_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inbound_email_id: Mapped[int] = mapped_column(ForeignKey("inbound_emails.id"), index=True)
    status: Mapped[str] = mapped_column(String(64), default="new", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    parsed_json: Mapped[str] = mapped_column(Text, default="{}")
    offer_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    pdf_path: Mapped[str] = mapped_column(String(500), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    inbound_email: Mapped[InboundEmail] = relationship(back_populates="draft")
    logs: Mapped[list["QuoteActionLog"]] = relationship(back_populates="draft")


class QuoteActionLog(Base):
    __tablename__ = "quote_action_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("quote_drafts.id"), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(128), default="system")
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    draft: Mapped[QuoteDraft] = relationship(back_populates="logs")

