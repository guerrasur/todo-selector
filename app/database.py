"""Base SQLite propia, fuera de la carpeta de la app (sobrevive a updates)."""

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


def carpeta_datos() -> Path:
    """Misma logica que Suipacha Loader, pero carpeta propia."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "TodoSelector"
    else:
        base = Path.home() / ".todo-selector"
    base.mkdir(parents=True, exist_ok=True)
    return base


DATOS = carpeta_datos()
DB_PATH = DATOS / "stock.db"
PERFIL_CHROME = DATOS / "chrome-profile"

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
