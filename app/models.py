import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, ForeignKey, DateTime
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


def gen_id():
    return uuid.uuid4().hex[:12]


class Group(Base):
    __tablename__ = "groups"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    invite_code = Column(String, unique=True, nullable=False, default=lambda: uuid.uuid4().hex[:8])
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    members = relationship("Member", back_populates="group", cascade="all, delete-orphan")
    expenses = relationship("Expense", back_populates="group", cascade="all, delete-orphan")


class Member(Base):
    __tablename__ = "members"

    id = Column(String, primary_key=True, default=gen_id)
    group_id = Column(String, ForeignKey("groups.id"), nullable=False)
    name = Column(String, nullable=False)

    group = relationship("Group", back_populates="members")


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(String, primary_key=True, default=gen_id)
    group_id = Column(String, ForeignKey("groups.id"), nullable=False)
    description = Column(String, nullable=False)
    amount = Column(Integer, nullable=False)  # minor units (paise)
    category = Column(String, nullable=False, default="other")
    paid_by_member_id = Column(String, ForeignKey("members.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    group = relationship("Group", back_populates="expenses")
    splits = relationship("ExpenseSplit", back_populates="expense", cascade="all, delete-orphan")


class ExpenseSplit(Base):
    """How much of an expense each member owes. Equal split for now,
    but this table makes unequal splits a future extension, not a rewrite."""
    __tablename__ = "expense_splits"

    id = Column(String, primary_key=True, default=gen_id)
    expense_id = Column(String, ForeignKey("expenses.id"), nullable=False)
    member_id = Column(String, ForeignKey("members.id"), nullable=False)
    share_amount = Column(Integer, nullable=False)  # minor units

    expense = relationship("Expense", back_populates="splits")
