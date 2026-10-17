"""
Pydantic schemas describe what the API accepts and returns.

A model (models.py) describes a database table, while a schema describes
the JSON in a request or response. They differ on purpose: not everything
in the DB should be exposed, and not every input is stored as is.
"""

from pydantic import BaseModel, ConfigDict


class TariffOut(BaseModel):
    # from_attributes=True lets the schema be built from an SQLAlchemy object
    # (it reads tariff.id, tariff.title, tariff.price).
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    # in kopecks
    price: int