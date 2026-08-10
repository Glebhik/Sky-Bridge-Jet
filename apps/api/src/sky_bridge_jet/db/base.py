from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base imported by future domain models and Alembic."""
