from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import session_scope
from ..models import Allocation, Asset, Portfolio
from ..schemas import (
    AllocationIn,
    HoldingOut,
    AccountHoldingOut,
    PositionOut,
    PortfolioAllocationsCreate,
    PortfolioCreate,
    RebalanceLeg,
    RebalanceSuggestion,
)
from ..services.rebalance import compute_holdings, compute_holdings_by_account, suggest_rebalance


router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _get_session() -> Session:
    with session_scope() as s:
        yield s


@router.post("/create")
def create_portfolio(payload: PortfolioCreate, session: Session = Depends(_get_session)):
    p = Portfolio(user_id=payload.user_id, name=payload.name, base_currency=payload.base_currency)
    session.add(p)
    session.flush()
    return {"portfolio_id": p.id}


@router.post("/allocations")
def set_allocations(payload: PortfolioAllocationsCreate, session: Session = Depends(_get_session)):
    portfolio = session.get(Portfolio, payload.portfolio_id)
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    # Clear existing
    session.query(Allocation).filter(Allocation.portfolio_id == payload.portfolio_id).delete()
    for a in payload.allocations:
        session.add(
            Allocation(
                portfolio_id=payload.portfolio_id,
                asset_id=a.asset_id,
                target_weight=a.target_weight,
                min_weight=a.min_weight,
                max_weight=a.max_weight,
                drift_threshold=a.drift_threshold,
            )
        )
    session.flush()
    return {"ok": True}


@router.get("/holdings", response_model=List[HoldingOut])
def get_holdings(user_id: int, session: Session = Depends(_get_session)):
    qty = compute_holdings(session, user_id)
    holdings: List[HoldingOut] = []
    if not qty:
        return holdings
    assets = {a.id: a for a in session.scalars(select(Asset).where(Asset.id.in_(list(qty.keys())))).all()}
    for aid, q in qty.items():
        a = assets.get(aid)
        if a is None:
            continue
        holdings.append(HoldingOut(asset_id=aid, symbol=a.symbol, quantity=q))
    return holdings


@router.get("/rebalance", response_model=RebalanceSuggestion)
def rebalance(portfolio_id: int, user_id: int, session: Session = Depends(_get_session)):
    portfolio = session.get(Portfolio, portfolio_id)
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    total_value, current_weights, target_weights, legs = suggest_rebalance(
        session, portfolio_id=portfolio_id, base_currency=portfolio.base_currency, user_id=user_id
    )

    legs_out: List[RebalanceLeg] = [
        RebalanceLeg(from_asset_id=l[0], to_asset_id=l[1], quantity_from=l[2]) for l in legs
    ]
    return RebalanceSuggestion(
        total_value=total_value,
        current_weights=current_weights,
        target_weights=target_weights,
        legs=legs_out,
    )


@router.get("/balances_by_account", response_model=List[AccountHoldingOut])
def balances_by_account(user_id: int, base_currency: str = "USD", session: Session = Depends(_get_session)):
    by_acct = compute_holdings_by_account(session, user_id)
    if not by_acct:
        return []

    # Map account_id to friendly name; get asset symbols and latest prices in base_currency
    from sqlalchemy import select
    from ..models import Account, Asset, Price

    account_rows = session.execute(select(Account.id, Account.name)).all()
    acct_name = {aid: name for aid, name in account_rows}

    # Map asset_id -> symbol
    asset_rows = session.execute(select(Asset.id, Asset.symbol)).all()
    asset_symbol = {int(aid): sym for aid, sym in asset_rows}

    # Latest price per asset in requested base currency
    price_rows = session.execute(
        select(Price.asset_id, Price.price)
        .where(Price.base_currency == base_currency)
        .order_by(Price.asset_id, Price.ts.desc())
    ).all()
    latest_price: Dict[int, float] = {}
    for aid, p in price_rows:
        if aid not in latest_price:
            latest_price[int(aid)] = float(p)

    out: List[AccountHoldingOut] = []
    for account_id, pos in by_acct.items():
        positions_out: List[PositionOut] = []
        total_value = 0.0
        for asset_id, qty in pos.items():
            sym = asset_symbol.get(int(asset_id), str(asset_id))
            price = latest_price.get(int(asset_id))
            value = (price * float(qty)) if price is not None else None
            if value is not None:
                total_value += value
            positions_out.append(
                PositionOut(
                    asset_id=int(asset_id),
                    symbol=sym,
                    quantity=float(qty),
                    price=price,
                    value=value,
                )
            )
        out.append(
            AccountHoldingOut(
                account_id=int(account_id),
                account_name=acct_name.get(int(account_id), f"Account {account_id}"),
                positions=positions_out,
                total_value=total_value if total_value > 0 else None,
            )
        )
    return out


@router.get("/balances_html", response_class=HTMLResponse)
def balances_html(user_id: int, base_currency: str = "USD", session: Session = Depends(_get_session)):
    # Reuse logic from balances_by_account
    from sqlalchemy import select
    from ..models import Account, Asset, Price

    by_acct = compute_holdings_by_account(session, user_id)
    account_rows = session.execute(select(Account.id, Account.name)).all()
    acct_name = {int(aid): name for aid, name in account_rows}
    asset_rows = session.execute(select(Asset.id, Asset.symbol)).all()
    asset_symbol = {int(aid): sym for aid, sym in asset_rows}
    price_rows = session.execute(
        select(Price.asset_id, Price.price)
        .where(Price.base_currency == base_currency)
        .order_by(Price.asset_id, Price.ts.desc())
    ).all()
    latest_price: Dict[int, float] = {}
    for aid, p in price_rows:
        if int(aid) not in latest_price:
            latest_price[int(aid)] = float(p)

    # Build flat rows: (account_name, symbol, qty, price, value)
    rows = []
    totals_by_account: Dict[str, float] = {}
    grand_total = 0.0
    for account_id, pos in by_acct.items():
        name = acct_name.get(int(account_id), f"Account {account_id}")
        acct_total = 0.0
        for asset_id, qty in pos.items():
            sym = asset_symbol.get(int(asset_id), str(asset_id))
            price = latest_price.get(int(asset_id))
            value = (price * float(qty)) if price is not None else None
            if value is not None:
                acct_total += value
            rows.append((name, sym, float(qty), price, value))
        totals_by_account[name] = acct_total
        grand_total += acct_total

    # Render simple HTML
    def fmt(x):
        return "-" if x is None else f"{x:,.2f}"

    html_rows = []
    last_account = None
    for name, sym, qty, price, value in rows:
        if last_account is not None and name != last_account:
            # subtotal row for previous account
            html_rows.append(
                f"<tr style='font-weight:600;background:#f6f6f6'><td colspan='4' style='text-align:right'>Subtotal</td><td>${fmt(totals_by_account[last_account])}</td></tr>"
            )
        html_rows.append(
            f"<tr><td>{name}</td><td>{sym}</td><td style='text-align:right'>{fmt(qty)}</td><td style='text-align:right'>{fmt(price)}</td><td style='text-align:right'>{fmt(value)}</td></tr>"
        )
        last_account = name
    if last_account is not None:
        html_rows.append(
            f"<tr style='font-weight:600;background:#f6f6f6'><td colspan='4' style='text-align:right'>Subtotal</td><td>${fmt(totals_by_account[last_account])}</td></tr>"
        )

    html = f"""
    <html>
    <head>
      <meta charset='utf-8' />
      <title>Balances by Account</title>
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
      <h2 style='margin-top:0'>Balances by Account (base: {base_currency})</h2>
      <table>
        <thead>
          <tr><th>Account</th><th>Asset</th><th>Quantity</th><th>Price ({base_currency})</th><th>Value ({base_currency})</th></tr>
        </thead>
        <tbody>
          {''.join(html_rows) if html_rows else '<tr><td colspan="5">No balances</td></tr>'}
        </tbody>
        <tfoot>
          <tr style='font-weight:700'><td colspan='4' style='text-align:right'>Grand Total</td><td>${fmt(grand_total)}</td></tr>
        </tfoot>
      </table>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
