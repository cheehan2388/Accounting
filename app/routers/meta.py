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

