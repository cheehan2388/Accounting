from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from .models import AccountType, AssetType, TransactionType


class UserCreate(BaseModel):
    email: Optional[str] = None
    base_currency: str = "USD"


class UserOut(BaseModel):
    id: int
    email: Optional[str]
    base_currency: str

    class Config:
        from_attributes = True


class CategoryCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None


class CategoryOut(BaseModel):
    id: int
    name: str
    parent_id: Optional[int]

    class Config:
        from_attributes = True


class AccountCreate(BaseModel):
    user_id: int
    name: str
    type: AccountType
    currency: str = "USD"


class AccountOut(BaseModel):
    id: int
    user_id: int
    name: str
    type: AccountType
    currency: str

    class Config:
        from_attributes = True


class AssetCreate(BaseModel):
    symbol: str
    name: str
    type: AssetType


class AssetOut(BaseModel):
    id: int
    symbol: str
    name: str
    type: AssetType

    class Config:
        from_attributes = True


class PriceCreate(BaseModel):
    asset_id: int
    price: float
    base_currency: str = "USD"
    ts: Optional[datetime] = None


class PriceOut(BaseModel):
    id: int
    asset_id: int
    price: float
    base_currency: str
    ts: datetime

    class Config:
        from_attributes = True


class ExpenseQuickAdd(BaseModel):
    user_id: int
    amount: float
    currency_asset_id: int
    category_id: int
    account_id: Optional[int] = None
    merchant: Optional[str] = None
    note: Optional[str] = None
    ts: Optional[datetime] = None


class TransactionOut(BaseModel):
    id: int
    user_id: int
    account_id: Optional[int]
    ts: datetime
    type: TransactionType
    category_id: Optional[int]
    from_asset_id: Optional[int]
    from_amount: Optional[float]
    to_asset_id: Optional[int]
    to_amount: Optional[float]
    fee_asset_id: Optional[int]
    fee_amount: Optional[float]
    merchant: Optional[str]
    note: Optional[str]

    class Config:
        from_attributes = True


class TradeCreate(BaseModel):
    user_id: int
    from_asset_id: int
    from_amount: float
    to_asset_id: int
    to_amount: float
    account_id: Optional[int] = None
    fee_asset_id: Optional[int] = None
    fee_amount: Optional[float] = 0
    ts: Optional[datetime] = None
    note: Optional[str] = None


class IncomeCreate(BaseModel):
    user_id: int
    to_asset_id: int
    to_amount: float
    account_id: int
    ts: Optional[datetime] = None
    note: Optional[str] = None


class PortfolioCreate(BaseModel):
    user_id: int
    name: str
    base_currency: str = "USD"


class AllocationIn(BaseModel):
    asset_id: int
    target_weight: float = Field(..., ge=0, le=1)
    min_weight: Optional[float] = None
    max_weight: Optional[float] = None
    drift_threshold: Optional[float] = None


class PortfolioAllocationsCreate(BaseModel):
    portfolio_id: int
    allocations: list[AllocationIn]


class HoldingOut(BaseModel):
    asset_id: int
    symbol: str
    quantity: float
    price: Optional[float] = None
    value: Optional[float] = None


class RebalanceLeg(BaseModel):
    from_asset_id: int
    to_asset_id: int
    quantity_from: float
    est_price_from: Optional[float] = None
    est_price_to: Optional[float] = None
    reason: Optional[str] = None


class RebalanceSuggestion(BaseModel):
    total_value: float
    current_weights: dict[int, float]
    target_weights: dict[int, float]
    legs: list[RebalanceLeg]

class PositionOut(BaseModel):
    asset_id: int
    symbol: str
    quantity: float
    price: Optional[float] = None
    value: Optional[float] = None


class AccountHoldingOut(BaseModel):
    account_id: int
    account_name: str
    positions: list[PositionOut]
    total_value: Optional[float] = None

