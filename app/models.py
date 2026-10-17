"""
Models describe database tables. All amounts are in kopecks, type int.
"""

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Tariff(Base):
    __tablename__ = "tariffs"

    # id is a short tariff name: "basic", "standard", "premium".
    # A string is clearer than a number: requests show which tariff is chosen.
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    
    # in kopecks: 9,900 RUB -> 990000
    price: Mapped[int] = mapped_column(Integer)