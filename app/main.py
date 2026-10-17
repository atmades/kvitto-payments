"""
Entry point: application setup and endpoints.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base, DbSession, SessionLocal, engine
from app.models import Tariff
from app.schemas import TariffOut

# Tariffs from the task: (id, title, price in kopecks).
TARIFFS = [
    ("basic", "Basic", 990000),  # 9 900 ₽
    ("standard", "Standard", 1990000),  # 19 900 ₽
    ("premium", "Premium", 2990000),  # 29 900 ₽
]


def seed_tariffs(db: Session) -> None:
    """
    Adds the tariffs that are not in the database yet.

    Each tariff is checked separately, so restarting the app
    never creates duplicates.
    """
    for tariff_id, title, price in TARIFFS:
        if db.get(Tariff, tariff_id) is None:
            db.add(Tariff(id=tariff_id, title=title, price=price))
    db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Code before yield runs on startup, code after it runs on shutdown.
    """
    # create tables if they do not exist yet
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_tariffs(db)
    yield


app = FastAPI(title="Kvitto Payments API", lifespan=lifespan)


@app.get("/tariffs", response_model=list[TariffOut])
def list_tariffs(db: DbSession) -> list[Tariff]:
    """
    List of tariffs sorted by price.
    """
    return list(db.scalars(select(Tariff).order_by(Tariff.price)))