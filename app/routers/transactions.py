from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import session_scope
from ..models import Category, Transaction, TransactionType
from ..schemas import ExpenseQuickAdd, TradeCreate, TransactionOut, IncomeCreate


router = APIRouter(prefix="/transactions", tags=["transactions"])


def _get_session() -> Session:
    with session_scope() as s:
        yield s


@router.post("/expense", response_model=TransactionOut)
def quick_add_expense(payload: ExpenseQuickAdd, session: Session = Depends(_get_session)):
    txn = Transaction(
        user_id=payload.user_id,
        account_id=payload.account_id,
        ts=payload.ts or datetime.utcnow(),
        type=TransactionType.expense,
        category_id=payload.category_id,
        from_asset_id=payload.currency_asset_id,
        from_amount=payload.amount,
        merchant=payload.merchant,
        note=payload.note,
    )
    session.add(txn)
    session.flush()
    return txn


@router.post("/trade", response_model=TransactionOut)
def create_trade(payload: TradeCreate, session: Session = Depends(_get_session)):
    txn = Transaction(
        user_id=payload.user_id,
        account_id=payload.account_id,
        ts=payload.ts or datetime.utcnow(),
        type=TransactionType.trade,
        from_asset_id=payload.from_asset_id,
        from_amount=payload.from_amount,
        to_asset_id=payload.to_asset_id,
        to_amount=payload.to_amount,
        fee_asset_id=payload.fee_asset_id,
        fee_amount=payload.fee_amount,
        note=payload.note,
    )
    session.add(txn)
    session.flush()
    return txn


@router.post("/income", response_model=TransactionOut)
def create_income(payload: IncomeCreate, session: Session = Depends(_get_session)):
    txn = Transaction(
        user_id=payload.user_id,
        account_id=payload.account_id,
        ts=payload.ts or datetime.utcnow(),
        type=TransactionType.income,
        to_asset_id=payload.to_asset_id,
        to_amount=payload.to_amount,
        note=payload.note,
    )
    session.add(txn)
    session.flush()
    return txn

@router.get("/today_totals")
def today_totals(user_id: int, session: Session = Depends(_get_session)):
    """Return today's totals for Eat and Buy categories (sum of expense amounts)."""
    today = date.today()
    start = datetime(today.year, today.month, today.day)
    end = datetime(today.year, today.month, today.day, 23, 59, 59)

    # Look up category ids for Eat, Buy
    cat_rows = session.execute(select(Category.id, Category.name).where(Category.name.in_(["Eat", "Buy"])) ).all()
    name_to_id = {name: cid for cid, name in cat_rows}

    def _sum_for(cat_name: str) -> float:
        cat_id: Optional[int] = name_to_id.get(cat_name)
        if not cat_id:
            return 0.0
        q = session.execute(
            select(func.coalesce(func.sum(Transaction.from_amount), 0)).where(
                Transaction.user_id == user_id,
                Transaction.type == TransactionType.expense,
                Transaction.category_id == cat_id,
                Transaction.ts >= start,
                Transaction.ts <= end,
            )
        ).scalar_one()
        return float(q or 0)

    return {"Eat": _sum_for("Eat"), "Buy": _sum_for("Buy")}

