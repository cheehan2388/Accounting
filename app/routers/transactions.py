from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import session_scope
from ..models import Category, Transaction, TransactionType, Asset, Account, Price
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
        category_id=payload.category_id,
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

    # Interpret the requested day in Taiwan time, then convert to UTC range
    tz = ZoneInfo("Asia/Taipei")
    start_local = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tz)
    end_local = start_local + timedelta(days=1) - timedelta(microseconds=1)
    start = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end = end_local.astimezone(timezone.utc).replace(tzinfo=None)

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
    base_currency: str = "USD",
    session: Session = Depends(_get_session),
):
    # Parse date (YYYY-MM-DD or YYYY/MM/DD)
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        d = datetime.strptime(date_str, "%Y/%m/%d").date()

    tz = ZoneInfo("Asia/Taipei")
    start_local = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tz)
    end_local = start_local + timedelta(days=1) - timedelta(microseconds=1)
    start = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end = end_local.astimezone(timezone.utc).replace(tzinfo=None)

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

    # Latest price per asset (currency) in requested base_currency
    price_rows = session.execute(
        select(Price.asset_id, Price.price)
        .where(Price.base_currency == base_currency)
        .order_by(Price.asset_id, Price.ts.desc())
    ).all()
    latest_price = {}
    for aid, p in price_rows:
        if int(aid) not in latest_price:
            latest_price[int(aid)] = float(p)

    # Build rows and total (in base currency)
    total_base = 0.0
    rows = []
    for t in txns:
        # Convert stored UTC (naive) to Taiwan time for display
        if t.ts:
            dt_local = t.ts.replace(tzinfo=timezone.utc).astimezone(tz)
            time_str = dt_local.strftime("%H:%M")
        else:
            time_str = ""
        cur = assets.get(t.from_asset_id)
        sym = cur.symbol if cur else ""
        amt = float(t.from_amount or 0)
        price = latest_price.get(int(t.from_asset_id)) if t.from_asset_id else None
        value_base = (amt * price) if price is not None else None
        if value_base is not None:
            total_base += value_base
        acct = accounts.get(t.account_id)
        acct_name = acct.name if acct else ""
        rows.append((time_str, acct_name, sym, amt, value_base, t.merchant or "", t.note or ""))

    # Render HTML table
    def fmt_money(x: float) -> str:
        return f"{x:,.2f}"

    trs = []
    for (time, acct, sym, amt, value_base, merchant, note) in rows:
        value_cell = '-' if value_base is None else f"{fmt_money(value_base)} {base_currency}"
        trs.append(
            f"<tr><td>{time}</td><td>{acct}</td><td style='text-align:right'>{fmt_money(amt)} {sym}</td><td style='text-align:right'>{value_cell}</td><td>{merchant}</td><td>{note}</td></tr>"
        )

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
          <tr><th>Time</th><th>Account</th><th>Amount</th><th>Value ({base_currency})</th><th>Merchant</th><th>Note</th></tr>
        </thead>
        <tbody>
          {''.join(trs)}
        </tbody>
        <tfoot>
          <tr style='font-weight:700'><td colspan='3' style='text-align:right'>Total</td><td style='text-align:right'>{fmt_money(total_base)} {base_currency}</td><td colspan='2'></td></tr>
        </tfoot>
      </table>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@router.get("/expense_trend_html", response_class=HTMLResponse)
def expense_trend_html(
    user_id: int,
    categories: str = "Buy,Bill,Eat",
    base_currency: str = "USD",
    session: Session = Depends(_get_session),
):
    """Line plot of daily expenses for selected categories (default: Buy, Bill, Eat), valued in base_currency.

    Dates are grouped in Taiwan time and shown from earliest expense date to today.
    """
    # Resolve category ids
    cat_names = [c.strip() for c in categories.split(",") if c.strip()]
    cat_rows = session.execute(select(Category.id, Category.name).where(Category.name.in_(cat_names))).all()
    name_to_id = {name: int(cid) for cid, name in cat_rows}

    # Latest price per asset for conversion to base
    price_rows = session.execute(
        select(Price.asset_id, Price.price)
        .where(Price.base_currency == base_currency)
        .order_by(Price.asset_id, Price.ts.desc())
    ).all()
    latest_price: dict[int, float] = {}
    for aid, p in price_rows:
        aid = int(aid)
        if aid not in latest_price:
            latest_price[aid] = float(p)

    # Pull relevant expense transactions
    stmt = select(Transaction).where(
        Transaction.user_id == user_id,
        Transaction.type == TransactionType.expense,
    )
    if name_to_id:
        stmt = stmt.where(Transaction.category_id.in_(list(name_to_id.values())))
    txns: list[Transaction] = list(session.scalars(stmt).all())

    # Aggregate daily sums per category (Taiwan time)
    tz = ZoneInfo("Asia/Taipei")
    daily: dict[str, dict[str, float]] = {}
    earliest_date = None
    for t in txns:
        if not t.ts:
            continue
        local_date = t.ts.replace(tzinfo=timezone.utc).astimezone(tz).date()
        date_key = local_date.strftime("%Y-%m-%d")
        # Convert amount to base
        price = latest_price.get(int(t.from_asset_id)) if t.from_asset_id else None
        value = float(t.from_amount or 0.0) * float(price) if price is not None else 0.0
        # Category label
        cat_label = None
        for name, cid in name_to_id.items():
            if t.category_id == cid:
                cat_label = name
                break
        if cat_label is None:
            cat_label = "Other"
        bucket = daily.setdefault(date_key, {})
        bucket[cat_label] = bucket.get(cat_label, 0.0) + value
        if earliest_date is None or local_date < earliest_date:
            earliest_date = local_date

    # Build continuous date labels from earliest to today
    from datetime import date as _date
    if earliest_date is None:
        earliest_date = _date.today()
    today_local = _date.today()
    labels = []
    cursor = earliest_date
    while cursor <= today_local:
        labels.append(cursor.strftime("%Y-%m-%d"))
        cursor = cursor + timedelta(days=1)

    # Prepare datasets per requested category in consistent order
    color_map = {
        "Eat": "#10b981",
        "Buy": "#f59e0b",
        "Bill": "#64748b",
    }
    datasets_js_parts = []
    for name in cat_names:
        series = [daily.get(d, {}).get(name, 0.0) for d in labels]
        vals_js = '[' + ','.join([f'{v:.2f}' for v in series]) + ']'
        color = color_map.get(name, "#2563eb")
        datasets_js_parts.append(
            f'{{label:"{name}",data:{vals_js},borderColor:"{color}",backgroundColor:"{color}33",tension:0.2,fill:false}}'
        )
    datasets_js = '[' + ','.join(datasets_js_parts) + ']'
    labels_js = '[' + ','.join([f'"{d}"' for d in labels]) + ']'

    html = f"""
    <html><head><meta charset='utf-8'><title>Expense Trends</title>
    <style>
      body {{ font-family: Arial, sans-serif; padding: 24px; }}
      .topbar {{ display:flex; gap:8px; align-items:center; margin-bottom:12px; }}
      .btn {{ display:inline-block; padding:8px 12px; background:#2563eb; color:#fff; text-decoration:none; border-radius:8px; }}
      .btn.secondary {{ background:#6b7280; }}
    </style></head>
    <body>
      <div class='topbar'>
        <a class='btn secondary' href='javascript:history.back()'>&larr; Back</a>
        <a class='btn' href='/app/'>Home</a>
      </div>
      <h2 style='margin-top:0'>Expense Trends ({base_currency})</h2>
      <canvas id='expLine' height='180'></canvas>
      <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
      <script>
        const labels = {labels_js};
        const datasets = {datasets_js};
        new Chart(document.getElementById('expLine').getContext('2d'), {{
          type: 'line',
          data: {{ labels, datasets }},
          options: {{ responsive: true, plugins: {{ legend: {{ position: 'bottom' }} }}, scales: {{ y: {{ beginAtZero: true }} }} }}
        }});
      </script>
    </body></html>
    """
    return HTMLResponse(content=html)


@router.get("/income_trend_html", response_class=HTMLResponse)
def income_trend_html(
    user_id: int,
    categories: str = "Salary,Investment,Startup",
    base_currency: str = "USD",
    session: Session = Depends(_get_session),
):
    """Line plot of monthly income for selected categories (default: Salary, Investment, Startup),
    valued in base_currency, with 3M moving averages and a stats table."""
    # Resolve category ids
    cat_names = [c.strip() for c in categories.split(",") if c.strip()]
    cat_rows = session.execute(select(Category.id, Category.name).where(Category.name.in_(cat_names))).all()
    name_to_id = {name: int(cid) for cid, name in cat_rows}

    # Latest price per asset for conversion to base
    price_rows = session.execute(
        select(Price.asset_id, Price.price)
        .where(Price.base_currency == base_currency)
        .order_by(Price.asset_id, Price.ts.desc())
    ).all()
    latest_price: dict[int, float] = {}
    for aid, p in price_rows:
        aid = int(aid)
        if aid not in latest_price:
            latest_price[aid] = float(p)

    # Pull relevant income transactions
    stmt = select(Transaction).where(
        Transaction.user_id == user_id,
        Transaction.type == TransactionType.income,
    )
    if name_to_id:
        stmt = stmt.where(Transaction.category_id.in_(list(name_to_id.values())))
    txns: list[Transaction] = list(session.scalars(stmt).all())

    # Aggregate monthly sums per category
    from collections import defaultdict
    monthly: dict[str, dict[str, float]] = {}
    months_list: set[str] = set()
    min_ym = None
    max_ym = None
    for t in txns:
        if not t.ts or not t.to_amount:
            continue
        ym = t.ts.strftime('%Y-%m')
        months_list.add(ym)
        # Convert amount to base
        price = latest_price.get(int(t.to_asset_id)) if t.to_asset_id else None
        value = float(t.to_amount or 0.0) * float(price) if price is not None else 0.0
        # Category label
        cat_label = None
        for name, cid in name_to_id.items():
            if t.category_id == cid:
                cat_label = name
                break
        if cat_label is None:
            cat_label = "Other"
        bucket = monthly.setdefault(ym, {})
        bucket[cat_label] = bucket.get(cat_label, 0.0) + value
        if min_ym is None or ym < min_ym:
            min_ym = ym
        if max_ym is None or ym > max_ym:
            max_ym = ym

    # Build continuous month labels from min_ym to max_ym (inclusive)
    labels = []
    if min_ym and max_ym:
        from datetime import datetime as _dt
        y, m = [int(x) for x in min_ym.split('-')]
        y2, m2 = [int(x) for x in max_ym.split('-')]
        cy, cm = y, m
        while True:
            labels.append(f"{cy:04d}-{cm:02d}")
            if cy == y2 and cm == m2:
                break
            cm += 1
            if cm > 12:
                cm = 1
                cy += 1

    # Prepare datasets and compute 3M moving averages + stats per category
    color_map = {
        "Salary": "#2563eb",
        "Startup": "#f59e0b",
        "Investment": "#10b981",
    }
    datasets_js_parts = []
    ma_datasets_js_parts = []
    stats_rows = []
    for name in cat_names:
        series = [monthly.get(ym, {}).get(name, 0.0) for ym in labels]
        # 3-month moving average
        ma3 = []
        for i in range(len(series)):
            window = series[max(0, i-2):i+1]
            ma3.append(sum(window) / len(window) if window else 0.0)
        # Stats
        import math
        n = len(series)
        mean_v = (sum(series) / n) if n else 0.0
        variance = (sum((x-mean_v)**2 for x in series) / n) if n else 0.0
        std_v = math.sqrt(variance)
        cv = (std_v / mean_v) if mean_v else 0.0
        last = series[-1] if series else 0.0
        prev = series[-2] if len(series) >= 2 else 0.0
        mom_pct = ((last - prev) / prev * 100.0) if prev else 0.0
        sharpe_like = (mean_v / std_v) if std_v else 0.0
        stats_rows.append((name, mean_v, std_v, cv, mom_pct, ma3[-1] if ma3 else 0.0, sharpe_like))

        vals_js = '[' + ','.join([f'{v:.2f}' for v in series]) + ']'
        ma_js = '[' + ','.join([f'{v:.2f}' for v in ma3]) + ']'
        color = color_map.get(name, "#8b5cf6")
        datasets_js_parts.append(
            f'{{label:"{name}",data:{vals_js},borderColor:"{color}",backgroundColor:"{color}33",tension:0.2,fill:false}}'
        )
        ma_datasets_js_parts.append(
            f'{{label:"{name} (MA3)",data:{ma_js},borderColor:"{color}",borderDash:[6,4],backgroundColor:"transparent",tension:0.2,fill:false}}'
        )
    datasets_js = '[' + ','.join(datasets_js_parts) + ']'
    ma_datasets_js = '[' + ','.join(ma_datasets_js_parts) + ']'
    labels_js = '[' + ','.join([f'"{d}"' for d in labels]) + ']'

    # Build stats table HTML
    stats_table_rows = ''.join([
        f"<tr><td>{n}</td><td style='text-align:right'>{mean:,.2f}</td><td style='text-align:right'>{std:,.2f}</td><td style='text-align:right'>{cv:,.2f}</td><td style='text-align:right'>{mom:,.1f}%</td><td style='text-align:right'>{ma:,.2f}</td><td style='text-align:right'>{sh:,.2f}</td></tr>"
        for (n, mean, std, cv, mom, ma, sh) in stats_rows
    ])

    html = f"""
    <html><head><meta charset='utf-8'><title>Income Trends</title>
    <style>
      body {{ font-family: Arial, sans-serif; padding: 24px; }}
      .topbar {{ display:flex; gap:8px; align-items:center; margin-bottom:12px; }}
      .btn {{ display:inline-block; padding:8px 12px; background:#2563eb; color:#fff; text-decoration:none; border-radius:8px; }}
      .btn.secondary {{ background:#6b7280; }}
      table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
      th, td {{ border: 1px solid #ddd; padding: 8px; }}
      th {{ background: #fafafa; text-align: left; }}
    </style></head>
    <body>
      <div class='topbar'>
        <a class='btn secondary' href='javascript:history.back()'>&larr; Back</a>
        <a class='btn' href='/app/'>Home</a>
      </div>
      <h2 style='margin-top:0'>Income Trends ({base_currency})</h2>
      <canvas id='incLine' height='180'></canvas>
      <canvas id='incMA' height='160' style='margin-top:16px'></canvas>
      <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
      <script>
        const labels = {labels_js};
        const datasets = {datasets_js};
        const maDatasets = {ma_datasets_js};
        new Chart(document.getElementById('incLine').getContext('2d'), {{
          type: 'line',
          data: {{ labels, datasets }},
          options: {{ responsive: true, plugins: {{ legend: {{ position: 'bottom' }} }}, scales: {{ y: {{ beginAtZero: true }} }} }}
        }});
        new Chart(document.getElementById('incMA').getContext('2d'), {{
          type: 'line',
          data: {{ labels, datasets: maDatasets }},
          options: {{ responsive: true, plugins: {{ legend: {{ position: 'bottom' }} }}, scales: {{ y: {{ beginAtZero: true }} }} }}
        }});
      </script>
      <h3>Category Stats</h3>
      <table>
        <thead>
          <tr><th>Category</th><th>Mean</th><th>Std Dev</th><th>CV</th><th>MoM %</th><th>MA3</th><th>Sharpe-like</th></tr>
        </thead>
        <tbody>
          {stats_table_rows or '<tr><td colspan="7">No data</td></tr>'}
        </tbody>
      </table>
    </body></html>
    """
    return HTMLResponse(content=html)


@router.get("/io_trend_html", response_class=HTMLResponse)
def io_trend_html(
    user_id: int,
    income_categories: str = "Salary,Investment,Startup",
    expense_categories: str = "Buy,Bill,Eat",
    base_currency: str = "USD",
    session: Session = Depends(_get_session),
):
    """Two-line chart: total income vs total outcome per day, plus spread summary.

    - Groups by Taiwan local date
    - Converts all amounts to base_currency using latest prices
    - Shows from earliest date to today
    """
    inc_names = [c.strip() for c in income_categories.split(",") if c.strip()]
    exp_names = [c.strip() for c in expense_categories.split(",") if c.strip()]

    # Resolve categories
    cat_rows = session.execute(select(Category.id, Category.name).where(Category.name.in_(inc_names + exp_names))).all()
    name_to_id = {name: int(cid) for cid, name in cat_rows}
    inc_ids = [name_to_id.get(n) for n in inc_names if name_to_id.get(n) is not None]
    exp_ids = [name_to_id.get(n) for n in exp_names if name_to_id.get(n) is not None]

    # Prices
    price_rows = session.execute(
        select(Price.asset_id, Price.price)
        .where(Price.base_currency == base_currency)
        .order_by(Price.asset_id, Price.ts.desc())
    ).all()
    latest_price: dict[int, float] = {}
    for aid, p in price_rows:
        aid = int(aid)
        if aid not in latest_price:
            latest_price[aid] = float(p)

    tz = ZoneInfo("Asia/Taipei")

    # Incomes
    inc_stmt = select(Transaction).where(Transaction.user_id == user_id, Transaction.type == TransactionType.income)
    if inc_ids:
        inc_stmt = inc_stmt.where(Transaction.category_id.in_(inc_ids))
    inc_txns: list[Transaction] = list(session.scalars(inc_stmt).all())
    daily_inc: dict[str, float] = {}
    earliest = None
    for t in inc_txns:
        if not t.ts or not t.to_amount:
            continue
        local_date = t.ts.replace(tzinfo=timezone.utc).astimezone(tz).date()
        date_key = local_date.strftime("%Y-%m-%d")
        price = latest_price.get(int(t.to_asset_id)) if t.to_asset_id else None
        value = float(t.to_amount or 0.0) * float(price) if price is not None else 0.0
        daily_inc[date_key] = daily_inc.get(date_key, 0.0) + value
        if earliest is None or local_date < earliest:
            earliest = local_date

    # Expenses
    exp_stmt = select(Transaction).where(Transaction.user_id == user_id, Transaction.type == TransactionType.expense)
    if exp_ids:
        exp_stmt = exp_stmt.where(Transaction.category_id.in_(exp_ids))
    exp_txns: list[Transaction] = list(session.scalars(exp_stmt).all())
    daily_exp: dict[str, float] = {}
    for t in exp_txns:
        if not t.ts or not t.from_amount:
            continue
        local_date = t.ts.replace(tzinfo=timezone.utc).astimezone(tz).date()
        date_key = local_date.strftime("%Y-%m-%d")
        price = latest_price.get(int(t.from_asset_id)) if t.from_asset_id else None
        value = float(t.from_amount or 0.0) * float(price) if price is not None else 0.0
        daily_exp[date_key] = daily_exp.get(date_key, 0.0) + value
        if earliest is None or local_date < earliest:
            earliest = local_date

    # Labels from earliest to today
    from datetime import date as _date
    if earliest is None:
        earliest = _date.today()
    today_local = _date.today()
    labels = []
    cursor = earliest
    while cursor <= today_local:
        labels.append(cursor.strftime("%Y-%m-%d"))
        cursor = cursor + timedelta(days=1)

    inc_series = [daily_inc.get(d, 0.0) for d in labels]
    exp_series = [daily_exp.get(d, 0.0) for d in labels]
    total_inc = sum(inc_series)
    total_exp = sum(exp_series)
    spread = total_inc - total_exp

    labels_js = '[' + ','.join([f'"{d}"' for d in labels]) + ']'
    inc_js = '[' + ','.join([f'{v:.2f}' for v in inc_series]) + ']'
    exp_js = '[' + ','.join([f'{v:.2f}' for v in exp_series]) + ']'

    html = f"""
    <html><head><meta charset='utf-8'><title>Income vs Outcome</title>
    <style>
      body {{ font-family: Arial, sans-serif; padding: 24px; }}
      .topbar {{ display:flex; gap:8px; align-items:center; margin-bottom:12px; }}
      .btn {{ display:inline-block; padding:8px 12px; background:#2563eb; color:#fff; text-decoration:none; border-radius:8px; }}
      .btn.secondary {{ background:#6b7280; }}
      .stat {{ display:inline-block; margin-right:16px; }}
    </style></head>
    <body>
      <div class='topbar'>
        <a class='btn secondary' href='javascript:history.back()'>&larr; Back</a>
        <a class='btn' href='/app/'>Home</a>
      </div>
      <h2 style='margin-top:0'>Income vs Outcome ({base_currency})</h2>
      <div style='margin:8px 0 16px'>
        <span class='stat'><strong>Total Income:</strong> {total_inc:,.2f} {base_currency}</span>
        <span class='stat'><strong>Total Outcome:</strong> {total_exp:,.2f} {base_currency}</span>
        <span class='stat'><strong>Spread:</strong> {spread:,.2f} {base_currency}</span>
      </div>
      <canvas id='ioLine' height='180'></canvas>
      <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
      <script>
        const labels = {labels_js};
        const ds = [
          {{ label: 'Income', data: {inc_js}, borderColor: '#10b981', backgroundColor: '#10b98133', tension: 0.2, fill: false }},
          {{ label: 'Outcome', data: {exp_js}, borderColor: '#ef4444', backgroundColor: '#ef444433', tension: 0.2, fill: false }}
        ];
        new Chart(document.getElementById('ioLine').getContext('2d'), {{
          type: 'line',
          data: {{ labels, datasets: ds }},
          options: {{ responsive: true, plugins: {{ legend: {{ position: 'bottom' }} }}, scales: {{ y: {{ beginAtZero: true }} }} }}
        }});
      </script>
    </body></html>
    """
    return HTMLResponse(content=html)

@router.get("/income_summary")
def income_summary(user_id: int, months: int = 6, base_currency: str = "USD", session: Session = Depends(_get_session)):
    """Return monthly income totals and category breakdown for the last N months (default 6), valued in base_currency using latest prices."""
    # Compute from first day months ago to end of current day in UTC
    today = date.today()
    start_month = date(today.year, today.month, 1)
    # naive month subtraction
    m = start_month.month - (months - 1)
    y = start_month.year
    while m <= 0:
        m += 12
        y -= 1
    range_start = datetime(y, m, 1)

    # Latest price per asset in requested base currency
    price_rows = session.execute(
        select(Price.asset_id, Price.price)
        .where(Price.base_currency == base_currency)
        .order_by(Price.asset_id, Price.ts.desc())
    ).all()
    latest_price: dict[int, float] = {}
    for aid, p in price_rows:
        aid = int(aid)
        if aid not in latest_price:
            latest_price[aid] = float(p)

    # Pull raw income transactions in range and aggregate in Python for flexible pricing
    rows = session.execute(
        select(
            Transaction.ts,
            Transaction.to_asset_id,
            Transaction.to_amount,
            Category.name,
        ).where(
            Transaction.user_id == user_id,
            Transaction.type == TransactionType.income,
            Transaction.ts >= range_start,
        ).join(Category, Category.id == Transaction.category_id, isouter=True)
    ).all()

    monthly: dict[str, float] = {}
    by_cat: dict[str, float] = {}
    monthly_by_cat: dict[str, dict[str, float]] = {}
    for ts, to_asset_id, to_amount, cat in rows:
        if not ts or not to_amount:
            continue
        ym = ts.strftime('%Y-%m')
        cat_name = cat or 'Uncategorized'
        price = latest_price.get(int(to_asset_id)) if to_asset_id else None
        value = float(to_amount) * float(price) if price is not None else 0.0
        monthly[ym] = monthly.get(ym, 0.0) + value
        by_cat[cat_name] = by_cat.get(cat_name, 0.0) + value
        inner = monthly_by_cat.setdefault(ym, {})
        inner[cat_name] = inner.get(cat_name, 0.0) + value

    # Average monthly income over available months in range
    months_present = len(monthly) if monthly else 0
    avg = (sum(monthly.values()) / months_present) if months_present else 0.0

    # Average per category for selected key categories (e.g., Startup, Investment)
    avg_by_category: dict[str, float] = {}
    if months_present:
        # compute average per category across months by summing per-month then / months_present
        # Build per-category monthly sums
        cat_names = set()
        for mkey in monthly_by_cat:
            cat_names.update(monthly_by_cat[mkey].keys())
        for cn in cat_names:
            s = 0.0
            for mkey in monthly_by_cat:
                s += monthly_by_cat[mkey].get(cn, 0.0)
            avg_by_category[cn] = s / months_present

    return {
        "monthly_totals": monthly,
        "by_category": by_cat,
        "monthly_by_category": monthly_by_cat,
        "average_monthly_income": avg,
        "average_by_category": avg_by_category,
        "base_currency": base_currency,
    }


@router.get("/income_summary_html", response_class=HTMLResponse)
def income_summary_html(user_id: int, months: int = 6, base_currency: str = "USD", session: Session = Depends(_get_session)):
    data = income_summary(user_id=user_id, months=months, base_currency=base_currency, session=session)
    ym = sorted(data["monthly_totals"].keys())
    rows = ''.join([f"<tr><td>{k}</td><td style='text-align:right'>{data['monthly_totals'][k]:,.2f} {base_currency}</td></tr>" for k in ym])
    cats = sorted(data["by_category"].items(), key=lambda kv: kv[0])
    bycat_rows = ''.join([f"<tr><td>{k}</td><td style='text-align:right'>{v:,.2f} {base_currency}</td></tr>" for k,v in cats])
    # Build JS data for charts
    labels_js = '[' + ','.join([f'"{k}"' for k in ym]) + ']'
    totals_js = '[' + ','.join([f'{data["monthly_totals"][k]:.2f}' for k in ym]) + ']'
    # Stacked datasets per category
    cat_names = sorted({c for m in data["monthly_by_category"].values() for c in m.keys()})
    colors = ['#2563eb','#10b981','#f59e0b','#ef4444','#8b5cf6','#14b8a6']
    datasets_js_parts = []
    for idx, cn in enumerate(cat_names):
        vals = [data["monthly_by_category"].get(k, {}).get(cn, 0.0) for k in ym]
        vals_js = '[' + ','.join([f'{v:.2f}' for v in vals]) + ']'
        color = colors[idx % len(colors)]
        datasets_js_parts.append(f'{{label:"{cn}",data:{vals_js},backgroundColor:"{color}"}}')
    datasets_js = '[' + ','.join(datasets_js_parts) + ']'
    # Averages for Startup/Investment
    mrr_labels = []
    mrr_values = []
    for key in ["Startup","Investment"]:
        if key in data["average_by_category"]:
            mrr_labels.append(key)
            mrr_values.append(f'{data["average_by_category"][key]:.2f}')
    mrr_labels_js = '[' + ','.join([f'"{x}"' for x in mrr_labels]) + ']'
    mrr_values_js = '[' + ','.join(mrr_values) + ']'
    html = f"""
    <html><head><meta charset='utf-8'><title>Income Summary</title>
    <style>
      body {{ font-family: Arial, sans-serif; padding: 24px; }}
      table {{ border-collapse: collapse; width: 100%; margin-bottom: 16px; }}
      th, td {{ border: 1px solid #ddd; padding: 8px; }}
      th {{ background: #fafafa; text-align: left; }}
      .topbar {{ display:flex; gap:8px; align-items:center; margin-bottom:12px; }}
      .btn {{ display:inline-block; padding:8px 12px; background:#2563eb; color:#fff; text-decoration:none; border-radius:8px; }}
      .btn.secondary {{ background:#6b7280; }}
    </style></head>
    <body>
      <div class='topbar'>
        <a class='btn secondary' href='javascript:history.back()'>&larr; Back</a>
        <a class='btn' href='/app/'>Home</a>
      </div>
      <h2 style='margin-top:0'>Income Summary (last {months} months, base: {base_currency})</h2>
      <div style='margin-bottom:16px;'>
        <canvas id='lineTotals' height='120'></canvas>
      </div>
      <div style='margin-bottom:16px;'>
        <canvas id='stackedByCat' height='160'></canvas>
      </div>
      <div style='margin-bottom:16px;'>
        <canvas id='avgMrr' height='120'></canvas>
      </div>
      <h3>Monthly Totals</h3>
      <table><thead><tr><th>Month</th><th>Total</th></tr></thead><tbody>{rows or '<tr><td colspan="2">No data</td></tr>'}</tbody></table>
      <h3>By Category</h3>
      <table><thead><tr><th>Category</th><th>Total</th></tr></thead><tbody>{bycat_rows or '<tr><td colspan="2">No data</td></tr>'}</tbody></table>
      <p><strong>Average Monthly Income:</strong> {data['average_monthly_income']:,.2f} {base_currency}</p>
      <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
      <script>
        const labels = {labels_js};
        const totals = {totals_js};
        const byCatDatasets = {datasets_js};
        const mrrLabels = {mrr_labels_js};
        const mrrValues = {mrr_values_js};
        new Chart(document.getElementById('lineTotals').getContext('2d'), {{
          type: 'line',
          data: {{ labels, datasets: [{{ label: 'Total ({base_currency})', data: totals, borderColor: '#2563eb', backgroundColor: 'rgba(37,99,235,0.2)', tension: 0.2 }}] }},
          options: {{ responsive: true, plugins: {{ legend: {{ display: true }} }}, scales: {{ y: {{ stacked: false, beginAtZero: true }} }} }}
        }});
        new Chart(document.getElementById('stackedByCat').getContext('2d'), {{
          type: 'bar',
          data: {{ labels, datasets: byCatDatasets }},
          options: {{ responsive: true, plugins: {{ legend: {{ position: 'bottom' }} }}, scales: {{ x: {{ stacked: true }}, y: {{ stacked: true, beginAtZero: true }} }} }}
        }});
        new Chart(document.getElementById('avgMrr').getContext('2d'), {{
          type: 'bar',
          data: {{ labels: mrrLabels, datasets: [{{ label: 'Average per Month ({base_currency})', data: mrrValues, backgroundColor: ['#10b981','#f59e0b'] }}] }},
          options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }} }}
        }});
      </script>
    </body></html>
    """
    return HTMLResponse(content=html)

