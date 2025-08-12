from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AccountType(str, Enum):
    cash = "cash"
    bank = "bank"
    exchange = "exchange"
    broker = "broker"


class AssetType(str, Enum):
    fiat = "fiat"
    crypto = "crypto"
    metal = "metal"
    stock = "stock"
    fund = "fund"


class TransactionType(str, Enum):
    expense = "expense"
    income = "income"
    trade = "trade"
    transfer = "transfer"
    rebalance = "rebalance"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    base_currency: Mapped[str] = mapped_column(String(10), default="USD")

    accounts: Mapped[list[Account]] = relationship(back_populates="user", cascade="all, delete-orphan")
    portfolios: Mapped[list[Portfolio]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[AccountType] = mapped_column(SAEnum(AccountType))
    currency: Mapped[str] = mapped_column(String(10), default="USD")

    user: Mapped[User] = relationship(back_populates="accounts")
    transactions: Mapped[list[Transaction]] = relationship(back_populates="account", cascade="all, delete-orphan")


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[AssetType] = mapped_column(SAEnum(AssetType))

    prices: Mapped[list[Price]] = relationship(back_populates="asset", cascade="all, delete-orphan")


class Price(Base):
    __tablename__ = "prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    price: Mapped[float] = mapped_column(Numeric(24, 10))
    base_currency: Mapped[str] = mapped_column(String(10), default="USD")

    asset: Mapped[Asset] = relationship(back_populates="prices")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"), nullable=True)

    parent: Mapped[Optional[Category]] = relationship(remote_side=[id])
    transactions: Mapped[list[Transaction]] = relationship(back_populates="category")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    ts: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    type: Mapped[TransactionType] = mapped_column(SAEnum(TransactionType))

    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"), nullable=True)

    from_asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("assets.id"), nullable=True)
    from_amount: Mapped[Optional[float]] = mapped_column(Numeric(24, 10), nullable=True)

    to_asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("assets.id"), nullable=True)
    to_amount: Mapped[Optional[float]] = mapped_column(Numeric(24, 10), nullable=True)

    fee_asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("assets.id"), nullable=True)
    fee_amount: Mapped[Optional[float]] = mapped_column(Numeric(24, 10), nullable=True)

    merchant: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    user: Mapped[User] = relationship()
    account: Mapped[Optional[Account]] = relationship(back_populates="transactions")
    category: Mapped[Optional[Category]] = relationship(back_populates="transactions")

    from_asset: Mapped[Optional[Asset]] = relationship(foreign_keys=[from_asset_id])
    to_asset: Mapped[Optional[Asset]] = relationship(foreign_keys=[to_asset_id])
    fee_asset: Mapped[Optional[Asset]] = relationship(foreign_keys=[fee_asset_id])


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    base_currency: Mapped[str] = mapped_column(String(10), default="USD")

    user: Mapped[User] = relationship(back_populates="portfolios")
    allocations: Mapped[list[Allocation]] = relationship(back_populates="portfolio", cascade="all, delete-orphan")


class Allocation(Base):
    __tablename__ = "allocations"
    __table_args__ = (UniqueConstraint("portfolio_id", "asset_id", name="uq_alloc_portfolio_asset"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"))
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    target_weight: Mapped[float] = mapped_column(Numeric(10, 6))
    min_weight: Mapped[Optional[float]] = mapped_column(Numeric(10, 6), nullable=True)
    max_weight: Mapped[Optional[float]] = mapped_column(Numeric(10, 6), nullable=True)
    drift_threshold: Mapped[Optional[float]] = mapped_column(Numeric(10, 6), nullable=True)

    portfolio: Mapped[Portfolio] = relationship(back_populates="allocations")
    asset: Mapped[Asset] = relationship()

