# prism/backend/app/database.py
from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=10,
    max_overflow=20,
    pool_timeout=60,
    echo=False,
)


@event.listens_for(engine, "connect")
def set_database_time_zone(dbapi_connection, connection_record):
    if not settings.DATABASE_TIME_ZONE:
        return
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute(f"SET time_zone = '{settings.DATABASE_TIME_ZONE}'")
        cursor.close()
    except Exception:
        pass

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
