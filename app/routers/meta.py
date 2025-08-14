from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import session_scope
from ..models import Account, AccountType, Asset, AssetType, Category, Price, User
from ..schemas import (
    AccountCreate,
    AccountOut,
    AccountUpdate,
    AssetCreate,
    AssetOut,
    CategoryCreate,
    CategoryOut,
    PriceCreate,
    PriceOut,
    UserCreate,
    UserOut,
)


router = APIRouter(prefix="/meta", tags=["meta"])


def _get_session() -> Session:
    with session_scope() as s:
        yield s


@router.post("/users", response_model=UserOut)
def create_user(payload: UserCreate, session: Session = Depends(_get_session)):
    user = User(email=payload.email, base_currency=payload.base_currency)
    session.add(user)
    session.flush()
    # Seed two default categories for this app flow
    for name in ("Eat", "Buy"):
        # Unique across table, so create only if absent
        existing = session.scalar(select(Category).where(Category.name == name))
        if not existing:
            session.add(Category(name=name))
    session.flush()
    return user


@router.post("/categories", response_model=CategoryOut)
def create_category(payload: CategoryCreate, session: Session = Depends(_get_session)):
    if session.scalar(select(Category).where(Category.name == payload.name)):
        raise HTTPException(status_code=409, detail="Category already exists")
    cat = Category(name=payload.name, parent_id=payload.parent_id)
    session.add(cat)
    session.flush()
    return cat


@router.get("/categories", response_model=List[CategoryOut])
def list_categories(session: Session = Depends(_get_session)):
    return list(session.scalars(select(Category)).all())


@router.post("/assets", response_model=AssetOut)
def create_asset(payload: AssetCreate, session: Session = Depends(_get_session)):
    if session.scalar(select(Asset).where(Asset.symbol == payload.symbol)):
        raise HTTPException(status_code=409, detail="Asset already exists")
    asset = Asset(symbol=payload.symbol, name=payload.name, type=payload.type)
    session.add(asset)
    session.flush()
    return asset


@router.get("/assets", response_model=List[AssetOut])
def list_assets(session: Session = Depends(_get_session)):
    return list(session.scalars(select(Asset)).all())


@router.post("/price", response_model=PriceOut)
def set_price(payload: PriceCreate, session: Session = Depends(_get_session)):
    price = Price(
        asset_id=payload.asset_id,
        price=payload.price,
        base_currency=payload.base_currency,
        ts=payload.ts,
    )
    session.add(price)
    session.flush()
    return price


@router.post("/accounts", response_model=AccountOut)
def create_account(payload: AccountCreate, session: Session = Depends(_get_session)):
    # Idempotent: if an account with the same user_id and name exists, return it
    existing = session.scalar(
        select(Account).where(Account.user_id == payload.user_id, Account.name == payload.name)
    )
    if existing:
        return existing
    account = Account(
        user_id=payload.user_id,
        name=payload.name,
        type=payload.type,
        currency=payload.currency,
    )
    session.add(account)
    session.flush()
    return account


@router.get("/accounts", response_model=List[AccountOut])
def list_accounts(session: Session = Depends(_get_session)):
    return list(session.scalars(select(Account)).all())


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int, session: Session = Depends(_get_session)):
    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    session.delete(account)
    session.flush()
    return {"ok": True}


@router.patch("/accounts/{account_id}", response_model=AccountOut)
def update_account(account_id: int, payload: AccountUpdate, session: Session = Depends(_get_session)):
    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if payload.name is not None:
        account.name = payload.name
    if payload.type is not None:
        account.type = payload.type
    if payload.currency is not None:
        account.currency = payload.currency
    session.flush()
    return account


@router.post("/categories/seed_income_categories", response_model=List[CategoryOut])
def seed_income_categories(session: Session = Depends(_get_session)):
    """Ensure common income categories exist: Salary, Startup, Investment."""
    wanted = ["Salary", "Startup", "Investment"]
    existing = {c.name for c in session.scalars(select(Category).where(Category.name.in_(wanted))).all()}
    created: List[Category] = []
    for name in wanted:
        if name not in existing:
            cat = Category(name=name)
            session.add(cat)
            created.append(cat)
    session.flush()
    # Return all income categories (created or pre-existing) for convenience
    cats = list(session.scalars(select(Category).where(Category.name.in_(wanted))).all())
    return cats

