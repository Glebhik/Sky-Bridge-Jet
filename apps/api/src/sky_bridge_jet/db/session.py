from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from sky_bridge_jet.core.config import get_settings

# This foundation uses synchronous SQLAlchemy end-to-end. FastAPI runs sync routes in
# its thread pool, while Alembic and request-scoped sessions share one clear model.
engine = create_engine(get_settings().database_url_for_sync, pool_pre_ping=True)
# Application services return persisted aggregates after committing their explicit
# write scope. Keeping those loaded values avoids a follow-up implicit read transaction.
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
