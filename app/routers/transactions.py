from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import session_scope
from ..models import Category, Transaction, TransactionType, Asset, Account
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


@router.get("/by_date", response_model=List[TransactionOut])
def list_expenses_by_date(
    user_id: int,
    date_str: str,
    category: Optional[str] = None,
    session: Session = Depends(_get_session),
):
    """List expense transactions for the given date (YYYY-MM-DD).

    Optional: filter by category name (e.g., "Eat" or "Buy").
    """
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        # Try alternate common formats
        try:
            d = datetime.strptime(date_str, "%Y/%m/%d").date()
        except ValueError:
            raise ValueError("Invalid date format. Use YYYY-MM-DD or YYYY/MM/DD.")

    start = datetime(d.year, d.month, d.day)
    end = datetime(d.year, d.month, d.day, 23, 59, 59)

    cat_id: Optional[int] = None
    if category:
        row = session.execute(select(Category.id).where(Category.name == category)).first()
        if row:
            cat_id = int(row[0])
        else:
            return []

    stmt = select(Transaction).where(
        Transaction.user_id == user_id,
        Transaction.type == TransactionType.expense,
        Transaction.ts >= start,
        Transaction.ts <= end,
    )
    if cat_id is not None:
        stmt = stmt.where(Transaction.category_id == cat_id)

    stmt = stmt.order_by(Transaction.ts.asc())
    results = list(session.scalars(stmt).all())
    return results


@router.get("/by_date_html", response_class=HTMLResponse)
def list_expenses_by_date_html(
    user_id: int,
    date_str: str,
    category: str = "Eat",
    session: Session = Depends(_get_session),
):
    # Parse date (YYYY-MM-DD or YYYY/MM/DD)
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        d = datetime.strptime(date_str, "%Y/%m/%d").date()

    start = datetime(d.year, d.month, d.day)
    end = datetime(d.year, d.month, d.day, 23, 59, 59)

    # Resolve category id (optional)
    cat_id = None
    if category:
        row = session.execute(select(Category.id).where(Category.name == category)).first()
        if row:
            cat_id = int(row[0])
        else:
            # Unknown category → empty list
            cat_id = -1

    stmt = select(Transaction).where(
        Transaction.user_id == user_id,
        Transaction.type == TransactionType.expense,
        Transaction.ts >= start,
        Transaction.ts <= end,
    )
    if cat_id and cat_id > 0:
        stmt = stmt.where(Transaction.category_id == cat_id)
    stmt = stmt.order_by(Transaction.ts.asc())
    txns: list[Transaction] = list(session.scalars(stmt).all())

    if not txns:
        html_empty = f"""
        <html><head><meta charset='utf-8'><title>Expenses {date_str}</title></head>
        <body style='font-family:Arial,sans-serif;padding:24px'>
          <h2>Expenses on {date_str} ({category})</h2>
          <p>No items.</p>
        </body></html>
        """
        return HTMLResponse(content=html_empty)

    # Collect asset/account names for display
    asset_ids = set([t.from_asset_id for t in txns if t.from_asset_id])
    assets = {a.id: a for a in session.scalars(select(Asset).where(Asset.id.in_(asset_ids))).all()}
    account_ids = set([t.account_id for t in txns if t.account_id])
    accounts = {a.id: a for a in session.scalars(select(Account).where(Account.id.in_(account_ids))).all()}

    # Build rows and total
    total = 0.0
    rows = []
    for t in txns:
        time_str = t.ts.strftime("%H:%M") if t.ts else ""
        cur = assets.get(t.from_asset_id)
        sym = cur.symbol if cur else ""
        amt = float(t.from_amount or 0)
        total += amt
        acct = accounts.get(t.account_id)
        acct_name = acct.name if acct else ""
        rows.append((time_str, acct_name, sym, amt, t.merchant or "", t.note or ""))

    # Render HTML table
    def fmt_money(x: float) -> str:
        return f"{x:,.2f}"

    trs = [
        f"<tr><td>{time}</td><td>{acct}</td><td style='text-align:right'>{fmt_money(amt)} {sym}</td><td>{merchant}</td><td>{note}</td></tr>"
        for (time, acct, sym, amt, merchant, note) in rows
    ]

    html = f"""
    <html>
    <head>
      <meta charset='utf-8' />
      <title>Expenses on {date_str} ({category})</title>
      <style>
        body {{ font-family: Arial, sans-serif; padding: 24px; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; }}
        th {{ background: #fafafa; text-align: left; }}
        .topbar {{ display:flex; gap:8px; align-items:center; margin-bottom:12px; }}
        .btn {{ display:inline-block; padding:8px 12px; background:#2563eb; color:#fff; text-decoration:none; border-radius:8px; }}
        .btn.secondary {{ background:#6b7280; }}
      </style>
    </head>
    <body>
      <div class='topbar'>
        <a class='btn secondary' href='javascript:history.back()'>&larr; Back</a>
        <a class='btn' href='/app/'>Home</a>
      </div>
      <h2 style='margin-top:0'>Expenses on {date_str} ({category})</h2>
      <table>
        <thead>
          <tr><th>Time</th><th>Account</th><th>Amount</th><th>Merchant</th><th>Note</th></tr>
        </thead>
        <tbody>
          {''.join(trs)}
        </tbody>
        <tfoot>
          <tr style='font-weight:700'><td colspan='2' style='text-align:right'>Total</td><td style='text-align:right'>{fmt_money(total)}</td><td colspan='2'></td></tr>
        </tfoot>
      </table>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

