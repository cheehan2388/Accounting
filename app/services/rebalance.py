from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Allocation, Asset, Price, Transaction, TransactionType


def _latest_price_map(session: Session, base_currency: str) -> Dict[int, float]:
    # Get latest price per asset in the requested base_currency. If none, skip.
    price_rows = session.execute(
        select(Price.asset_id, Price.price).where(Price.base_currency == base_currency).order_by(Price.asset_id, Price.ts.desc())
    ).all()
    latest: Dict[int, float] = {}
    for asset_id, price in price_rows:
        if asset_id not in latest:  # first occurrence is latest due to desc order within asset grouping
            latest[asset_id] = float(price)
    return latest


def compute_holdings(session: Session, user_id: int) -> Dict[int, float]:
    """Aggregate quantities from trade/rebalance transactions for a user by asset_id."""
    rows = session.execute(
        select(
            Transaction.from_asset_id,
            Transaction.from_amount,
            Transaction.to_asset_id,
            Transaction.to_amount,
        ).where(
            Transaction.user_id == user_id,
            Transaction.type.in_([TransactionType.trade, TransactionType.rebalance]),
        )
    ).all()
    qty: Dict[int, float] = defaultdict(float)
    for from_asset_id, from_amount, to_asset_id, to_amount in rows:
        if from_asset_id and from_amount:
            qty[int(from_asset_id)] -= float(from_amount)
        if to_asset_id and to_amount:
            qty[int(to_asset_id)] += float(to_amount)
    # Remove near-zero dust
    return {aid: q for aid, q in qty.items() if abs(q) > 1e-10}


def compute_holdings_by_account(session: Session, user_id: int) -> Dict[int, Dict[int, float]]:
    """Aggregate quantities by account and asset for a user.

    Includes trade, rebalance, and expense/income types so that cash decreases
    when you record expenses and increases on incomes.

    Returns a nested dict: {account_id: {asset_id: quantity}}.
    """
    rows = session.execute(
        select(
            Transaction.account_id,
            Transaction.type,
            Transaction.from_asset_id,
            Transaction.from_amount,
            Transaction.to_asset_id,
            Transaction.to_amount,
        ).where(
            Transaction.user_id == user_id,
            Transaction.type.in_(
                [
                    TransactionType.trade,
                    TransactionType.rebalance,
                    TransactionType.expense,
                    TransactionType.income,
                ]
            ),
        )
    ).all()

    by_account: Dict[int, Dict[int, float]] = {}
    for account_id, txn_type, from_asset_id, from_amount, to_asset_id, to_amount in rows:
        if account_id is None:
            # Skip transactions that are not tied to a specific account for this view
            # (you can still see them in the aggregate holdings endpoint).
            continue
        acct_map = by_account.setdefault(int(account_id), {})

        def _add(asset_id: Optional[int], delta: float) -> None:
            if not asset_id or abs(delta) <= 0:
                return
            aid = int(asset_id)
            acct_map[aid] = float(acct_map.get(aid, 0.0) + delta)

        if txn_type in (TransactionType.trade, TransactionType.rebalance):
            if from_asset_id and from_amount:
                _add(from_asset_id, -float(from_amount))
            if to_asset_id and to_amount:
                _add(to_asset_id, float(to_amount))
        elif txn_type == TransactionType.expense:
            # Cash (from_asset) goes down by the spent amount
            if from_asset_id and from_amount:
                _add(from_asset_id, -float(from_amount))
        elif txn_type == TransactionType.income:
            # Cash (to_asset) increases by the received amount
            if to_asset_id and to_amount:
                _add(to_asset_id, float(to_amount))

    # Remove near-zero dust
    cleaned: Dict[int, Dict[int, float]] = {}
    for account_id, m in by_account.items():
        filtered = {aid: q for aid, q in m.items() if abs(q) > 1e-10}
        if filtered:
            cleaned[account_id] = filtered
    return cleaned

def compute_values(weights_assets: Iterable[int], quantities: Dict[int, float], price_map: Dict[int, float]) -> Tuple[float, Dict[int, float]]:
    values: Dict[int, float] = {}
    total_value = 0.0
    for asset_id in weights_assets:
        q = quantities.get(asset_id, 0.0)
        p = price_map.get(asset_id)
        if p is None:
            continue  # skip assets without prices
        v = q * p
        values[asset_id] = v
        total_value += v
    return total_value, values


def suggest_rebalance(
    session: Session,
    portfolio_id: int,
    base_currency: str,
    user_id: int,
) -> Tuple[float, Dict[int, float], Dict[int, float], List[Tuple[int, int, float]]]:
    """Return total_value, current_weights, target_weights, and list of (from_asset_id, to_asset_id, qty_from)."""
    allocations: list[Allocation] = session.scalars(
        select(Allocation).where(Allocation.portfolio_id == portfolio_id)
    ).all()
    if not allocations:
        return 0.0, {}, {}, []

    target_weights = {a.asset_id: float(a.target_weight) for a in allocations}
    asset_ids = list(target_weights.keys())

    price_map = _latest_price_map(session, base_currency)
    quantities = compute_holdings(session, user_id)

    total_value, values = compute_values(asset_ids, quantities, price_map)
    if total_value <= 0:
        return 0.0, {}, target_weights, []

    current_weights = {aid: (values.get(aid, 0.0) / total_value) for aid in asset_ids}

    # Build lists of deltas
    deltas = {aid: target_weights[aid] * total_value - values.get(aid, 0.0) for aid in asset_ids}
    sources: List[Tuple[int, float]] = [(aid, -delta) for aid, delta in deltas.items() if delta < -1e-6]
    dests: List[Tuple[int, float]] = [(aid, delta) for aid, delta in deltas.items() if delta > 1e-6]

    # Greedy pairing sources to destinations based on value deltas, convert to qty using from-asset price
    legs: List[Tuple[int, int, float]] = []
    s_idx, d_idx = 0, 0
    sources.sort(key=lambda x: x[1], reverse=True)
    dests.sort(key=lambda x: x[1], reverse=True)

    while s_idx < len(sources) and d_idx < len(dests):
        from_aid, from_value = sources[s_idx]
        to_aid, to_value = dests[d_idx]

        move_value = min(from_value, to_value)
        from_price = price_map.get(from_aid)
        if not from_price or from_price <= 0:
            break
        qty_from = move_value / from_price
        legs.append((from_aid, to_aid, qty_from))

        # Update remaining value to move
        sources[s_idx] = (from_aid, from_value - move_value)
        dests[d_idx] = (to_aid, to_value - move_value)
        if sources[s_idx][1] <= 1e-6:
            s_idx += 1
        if dests[d_idx][1] <= 1e-6:
            d_idx += 1

    return total_value, current_weights, target_weights, legs

    