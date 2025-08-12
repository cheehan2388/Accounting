from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from .db import engine, session_scope
from .models import Base
from .routers import meta, portfolio, transactions


def init_db() -> None:
    # Create tables if not exist
    Base.metadata.create_all(bind=engine)


init_db()

app = FastAPI(title="Money App MVP", version="0.1.0")

app.include_router(meta.router)
app.include_router(transactions.router)
app.include_router(portfolio.router)


@app.get("/")
def root():
    return {"ok": True}

