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
    _agregar_columnas_faltantes()


def _agregar_columnas_faltantes():
    """Le agrega a las tablas ya creadas las columnas nuevas del modelo.

    `create_all` crea las tablas que faltan pero NO toca las que ya existen:
    en una base ya usada, una columna nueva del modelo no aparece nunca y
    todas las consultas empiezan a fallar con "no such column".

    Este proyecto no tiene migraciones y no las amerita, pero sin esto la
    unica salida era borrar la base del usuario y perderle el historial.
    Alcanza con ALTER TABLE ADD COLUMN, que en SQLite es barato y no
    reescribe la tabla. Solo agrega: nunca borra ni cambia una columna.
    """
    import logging
    from sqlalchemy import inspect, text

    log = logging.getLogger("database")
    inspector = inspect(engine)

    with engine.begin() as con:
        for tabla in Base.metadata.sorted_tables:
            existentes = {c["name"] for c in inspector.get_columns(tabla.name)}
            for columna in tabla.columns:
                if columna.name in existentes:
                    continue

                tipo = columna.type.compile(engine.dialect)
                sql = f'ALTER TABLE {tabla.name} ADD COLUMN {columna.name} {tipo}'

                # El default del modelo lo aplica Python al crear filas; para
                # las que YA existen hace falta decirselo a SQLite.
                por_defecto = getattr(columna.default, "arg", None)
                if isinstance(por_defecto, bool):
                    sql += f" DEFAULT {1 if por_defecto else 0}"
                elif isinstance(por_defecto, (int, float)):
                    sql += f" DEFAULT {por_defecto}"
                elif isinstance(por_defecto, str):
                    sql += f" DEFAULT '{por_defecto}'"

                con.execute(text(sql))
                log.info("Columna nueva en %s: %s", tabla.name, columna.name)
