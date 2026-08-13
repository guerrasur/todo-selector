"""Prueba el backup automatico de la base. Sin navegador y sin tocar tu base.

    py pruebas/probar_backup.py

Todo pasa en una carpeta temporal: se apunta HOME/LOCALAPPDATA ahi ANTES de
importar `app.*`, asi `DATOS` (y con el la base y la carpeta de backups) cae
adentro y la base real del usuario no se toca ni se lee.

Lo delicado del backup no es copiar: es que la copia sirva el dia que haga
falta. Por eso se prueba que el archivo sea una base abrible de verdad, que
no quede nunca un `.tmp` haciendose pasar por backup, y que la poda no se
lleve puesto el mas nuevo.
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

TEMPORAL = tempfile.mkdtemp(prefix="todoselector-backup-")
os.environ["HOME"] = TEMPORAL
os.environ["LOCALAPPDATA"] = TEMPORAL

from app import backup                                          # noqa: E402
from app.backup import CARPETA, CUANTOS_GUARDAR, hacer_backup   # noqa: E402
from app.database import DB_PATH, init_db                       # noqa: E402

fallos = []


def revisar(condicion, titulo):
    print(("  OK    " if condicion else "  FALLA ") + titulo)
    if not condicion:
        fallos.append(titulo)


def es_una_base_de_verdad(archivo: Path) -> bool:
    """Que abra y tenga las tablas de la app, no que pese algo."""
    try:
        con = sqlite3.connect(str(archivo))
        try:
            tablas = {f[0] for f in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return False
    return {"productos", "estados_item", "operaciones"} <= tablas


def envejecer(archivo: Path, horas: float):
    """Le corre la fecha de modificacion para atras, sin tocar el reloj."""
    viejo = time.time() - horas * 3600
    os.utime(archivo, (viejo, viejo))


def vaciar_carpeta():
    for archivo in CARPETA.glob("*"):
        archivo.unlink()


def se_crea_el_del_dia():
    print("\n== Se crea el backup del dia ==")
    hoy = date(2026, 8, 13)

    destino = hacer_backup(hoy=hoy)

    revisar(destino is not None and destino.exists(),
            "hacer_backup deja el archivo del dia")
    revisar(destino.name == "stock_2026-08-13.db",
            "el nombre lleva la fecha: stock_<fecha>.db")
    revisar(destino.parent == CARPETA,
            "queda en la carpeta 'backups' de los datos, no en el repo")
    revisar(es_una_base_de_verdad(destino),
            "la copia abre como base SQLite y tiene las tablas de la app")
    revisar(list(CARPETA.glob("*.tmp")) == [],
            "no queda ningun .tmp despues de una copia que salio bien")


def no_se_duplica():
    print("\n== El del dia no se rehace porque si ==")
    hoy = date(2026, 8, 13)
    primero = hacer_backup(hoy=hoy)
    envejecer(primero, horas=5)
    marca_vieja = primero.stat().st_mtime_ns

    segundo = hacer_backup(hoy=hoy)

    revisar(segundo == primero, "devuelve el mismo archivo, no uno nuevo")
    revisar(segundo.stat().st_mtime_ns == marca_vieja,
            "sin refrescar_horas no lo reescribe, aunque haya quedado viejo")
    revisar(len(list(CARPETA.glob("stock_*.db"))) == 1,
            "no aparece un segundo backup para el mismo dia")


def se_rehace_si_vencio():
    print("\n== Se rehace el que quedo viejo ==")
    hoy = date(2026, 8, 13)
    destino = hacer_backup(hoy=hoy)

    envejecer(destino, horas=4)
    vencido = destino.stat().st_mtime_ns
    rehecho = hacer_backup(hoy=hoy, refrescar_horas=3)

    revisar(rehecho.stat().st_mtime_ns > vencido,
            "con refrescar_horas=3 y 4 horas de viejo, lo rehace")
    revisar(es_una_base_de_verdad(rehecho),
            "el rehecho sigue siendo una base abrible")

    envejecer(destino, horas=1)
    fresco = destino.stat().st_mtime_ns
    hacer_backup(hoy=hoy, refrescar_horas=3)

    revisar(destino.stat().st_mtime_ns == fresco,
            "con 1 hora de viejo y umbral de 3, lo deja como esta")
    revisar(len(list(CARPETA.glob("stock_*.db"))) == 1,
            "rehacer pisa el del dia, no acumula copias")


def la_poda_deja_treinta():
    print("\n== La poda deja los ultimos 30 ==")
    vaciar_carpeta()
    primero = date(2026, 1, 1)
    for i in range(40):
        fecha = (primero + timedelta(days=i)).isoformat()
        (CARPETA / f"stock_{fecha}.db").write_bytes(b"")

    backup._podar()

    quedaron = sorted(p.name for p in CARPETA.glob("stock_*.db"))
    revisar(len(quedaron) == CUANTOS_GUARDAR,
            f"de 40 copias quedan {CUANTOS_GUARDAR}")
    revisar("stock_2026-02-09.db" in quedaron,
            "queda la mas nueva (la del dia 40)")
    revisar("stock_2026-01-01.db" not in quedaron,
            "se va la mas vieja (la del dia 1)")
    revisar(quedaron[0] == "stock_2026-01-11.db",
            "se van justo las 10 mas viejas, no un rango al azar")


def los_tmp_huerfanos_se_limpian():
    print("\n== Los .tmp que quedaron colgados se limpian ==")
    vaciar_carpeta()
    # Asi queda el disco si la app se cierra en el medio de una copia: un .tmp
    # incompleto que no sirve para restaurar y que nadie va a mirar nunca.
    huerfano = CARPETA / "stock_2026-08-12.db.tmp"
    huerfano.write_bytes(b"copia a medio escribir")

    destino = hacer_backup(hoy=date(2026, 8, 13))

    revisar(not huerfano.exists(), "el .tmp huerfano de otra corrida se borra")
    revisar(list(CARPETA.glob("*.tmp")) == [],
            "no queda ningun .tmp en la carpeta")
    revisar(destino.exists() and es_una_base_de_verdad(destino),
            "el backup del dia se hizo igual")


def sin_base_no_inventa_nada():
    print("\n== Sin base todavia no hay nada que copiar ==")
    vaciar_carpeta()
    guardada = Path(str(DB_PATH) + ".guardada")
    DB_PATH.replace(guardada)
    try:
        # Instalacion recien bajada: init_db todavia no corrio.
        resultado = hacer_backup(hoy=date(2026, 8, 13))
    finally:
        guardada.replace(DB_PATH)

    revisar(resultado is None, "devuelve None en vez de un archivo vacio")
    revisar(list(CARPETA.glob("stock_*.db")) == [],
            "no deja un backup de una base que no existe")


def el_hilo_no_bloquea():
    print("\n== El hilo periodico ==")
    hilo = backup.iniciar_backups_periodicos()

    revisar(hilo.daemon,
            "es daemon: cerrar la app no espera a que termine de dormir")
    revisar(hilo.is_alive(), "arranca y devuelve el control enseguida")


def main():
    init_db()
    CARPETA.mkdir(parents=True, exist_ok=True)
    try:
        se_crea_el_del_dia()
        no_se_duplica()
        se_rehace_si_vencio()
        la_poda_deja_treinta()
        los_tmp_huerfanos_se_limpian()
        sin_base_no_inventa_nada()
        el_hilo_no_bloquea()
    finally:
        shutil.rmtree(TEMPORAL, ignore_errors=True)

    print("\n" + ("TODO OK" if not fallos else f"{len(fallos)} FALLAS: {fallos}"))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
