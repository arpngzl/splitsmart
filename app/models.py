import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, ForeignKey, DateTime, Boolean
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


def gen_id():
    return uuid.uuid4().hex[:12]


def now_utc():
    return datetime.now(timezone.utc)


class Group(Base):
    __tablename__ = "groups"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    emoji = Column(String, nullable=False, default="🧾")
    invite_code = Column(String, unique=True, nullable=False, default=lambda: uuid.uuid4().hex[:8])
    created_at = Column(DateTime, default=now_utc)

    members = relationship("Member", back_populates="group", cascade="all, delete-orphan")
    expenses = relationship("Expense", back_populates="group", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="group", cascade="all, delete-orphan")
    budget = relationship("Budget", back_populates="group", uselist=False, cascade="all, delete-orphan")


class Member(Base):
    __tablename__ = "members"

    id = Column(String, primary_key=True, default=gen_id)
    group_id = Column(String, ForeignKey("groups.id"), nullable=False)
    name = Column(String, nullable=False)
    avatar_color = Column(String, nullable=False, default="#ff8fa3")

    group = relationship("Group", back_populates="members")


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(String, primary_key=True, default=gen_id)
    group_id = Column(String, ForeignKey("groups.id"), nullable=False)
    description = Column(String, nullable=False)
    amount = Column(Integer, nullable=False)  # minor units (paise)
    category = Column(String, nullable=False, default="other")
    paid_by_member_id = Column(String, ForeignKey("members.id"), nullable=False)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime, default=now_utc)

    group = relationship("Group", back_populates="expenses")
    splits = relationship("ExpenseSplit", back_populates="expense", cascade="all, delete-orphan")


class ExpenseSplit(Base):
    """How much of an expense each member owes. Supports equal or custom splits."""
    __tablename__ = "expense_splits"

    id = Column(String, primary_key=True, default=gen_id)
    expense_id = Column(String, ForeignKey("expenses.id"), nullable=False)
    member_id = Column(String, ForeignKey("members.id"), nullable=False)
    share_amount = Column(Integer, nullable=False)  # minor units

    expense = relationship("Expense", back_populates="splits")


class Payment(Base):
    """A real-world settle-up payment recorded between two members."""
    __tablename__ = "payments"

    id = Column(String, primary_key=True, default=gen_id)
    group_id = Column(String, ForeignKey("groups.id"), nullable=False)
    from_member_id = Column(String, ForeignKey("members.id"), nullable=False)
    to_member_id = Column(String, ForeignKey("members.id"), nullable=False)
    amount = Column(Integer, nullable=False)  # minor units
    note = Column(String, nullable=True)
    created_at = Column(DateTime, default=now_utc)

    group = relationship("Group", back_populates="payments")


class Budget(Base):
    """Optional monthly spending target for a group, used for AI budget alerts."""
    __tablename__ = "budgets"

    id = Column(String, primary_key=True, default=gen_id)
    group_id = Column(String, ForeignKey("groups.id"), unique=True, nullable=False)
    monthly_limit = Column(Integer, nullable=False)  # minor units

    group = relationship("Group", back_populates="budget")
