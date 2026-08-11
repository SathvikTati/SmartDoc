from typing import Annotated

from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from port6.config import DATABASE_URL, database_config


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=database_config.get(
        "pool_pre_ping",
        True,
    ),
)


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


Base = declarative_base()


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


db_dependency = Annotated[
    Session,
    Depends(get_db),
]