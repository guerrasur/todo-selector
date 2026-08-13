"""Copia de seguridad diaria de la base, sin que el usuario haga nada.

La base vive fuera de la carpeta de la app (`~/.todo-selector/stock.db`), asi
que sobrevive a los updates, pero no sobrevive a un disco lleno, a un cierre
feo de Windows ni a un borrado por error. Lo que se pierde ahi no es poco: el
catalogo entero con los alias vinculados a mano en la pantalla Carta, los
ajustes de sucursal y el historial de operaciones.

Dos decisiones que importan:

1. **Se copia con la API de backup de SQLite** (`Connection.backup`), no
   copiando el archivo. La app escribe en la base mientras el hilo del backup
   corre; copiar el archivo a mano en el medio de una transaccion da una copia
   corrupta que recien se descubre el dia que hace falta. La API online
   trabaja pagina por pagina y se entiende con el motor.

2. **Se escribe a un `.tmp` y recien al final se renombra** (`Path.replace`,
   que es atomico dentro del mismo directorio). Si la app se cierra en el
   medio, lo que queda tirado es el `.tmp`, y el backup de ayer sigue entero.
   Nunca hay un `stock_<fecha>.db` a medio escribir haciendose pasar por
   bueno.

No tiene pantalla ni endpoint: los backups quedan en `~/.todo-selector/
backups/` y se recuperan copiando el que se quiera arriba de `stock.db` con
la app cerrada.
"""

import sqlite3
import threading
import time
from datetime import date
from pathlib import Path

from .database import DATOS, DB_PATH

CARPETA = DATOS / "backups"

# Cada cuanto se rehace el backup del dia mientras la app esta abierta. La app
# queda prendida todo el turno: sin esto, el backup de un dia de doce horas
# seria el de la primera vez que se abrio la pantalla.
REFRESCO_HORAS = 3

# Un mes de historia. Cada copia pesa lo que la base (chica: catalogo, estados
# y operaciones), asi que el limite es para no acumular para siempre, no por
# espacio.
CUANTOS_GUARDAR = 30


def hacer_backup(hoy=None, refrescar_horas=None):
    """Deja el backup del dia hecho. Devuelve su ruta, o None si no hay base.

    Si el del dia ya existe no lo rehace, salvo que se pase `refrescar_horas`
    y el archivo haya quedado mas viejo que ese umbral.

    `hoy` se puede inyectar (las pruebas lo usan para fabricar dias distintos
    sin tocar el reloj del sistema).
    """
    if not DB_PATH.exists():
        # Instalacion recien bajada: todavia no hay nada que guardar. No se
        # crea ni la carpeta, para no dejar rastros de algo que no paso.
        return None

    fecha = (hoy or date.today()).isoformat()
    CARPETA.mkdir(parents=True, exist_ok=True)
    destino = CARPETA / f"stock_{fecha}.db"

    if destino.exists() and not _vencido(destino, refrescar_horas):
        return destino

    provisorio = CARPETA / f"{destino.name}.tmp"
    _copiar(DB_PATH, provisorio)
    provisorio.replace(destino)

    _podar()
    return destino


def iniciar_backups_periodicos():
    """Hilo daemon que rehace el backup del dia cada REFRESCO_HORAS.

    Daemon: cuando se cierra la app el hilo se va con ella, sin colgar el
    cierre esperando a que termine de dormir.

    Todo lo de adentro va envuelto: **el backup nunca puede voltear la app**.
    Que falle una copia es molesto; que la pantalla de apagar productos no
    levante porque el disco estaba lleno es perder el turno entero.
    """
    def rutina():
        while True:
            time.sleep(REFRESCO_HORAS * 3600)
            try:
                hacer_backup(refrescar_horas=REFRESCO_HORAS)
            except Exception as e:
                print(f"[backup] no se pudo hacer la copia de la base: {e}")

    hilo = threading.Thread(target=rutina, daemon=True, name="backups")
    hilo.start()
    return hilo


def _vencido(destino, refrescar_horas):
    """True si el backup del dia quedo mas viejo que el umbral pedido."""
    if refrescar_horas is None:
        return False
    try:
        edad = time.time() - destino.stat().st_mtime
    except OSError:
        return True
    return edad > refrescar_horas * 3600


def _copiar(origen: Path, destino: Path):
    """Copia la base con la API online de SQLite, tolerando escrituras."""
    con_origen = sqlite3.connect(str(origen))
    try:
        con_destino = sqlite3.connect(str(destino))
        try:
            con_origen.backup(con_destino)
        finally:
            con_destino.close()
    finally:
        con_origen.close()


def _podar():
    """Limpia los .tmp que quedaron colgados y deja los ultimos backups.

    Los `.tmp` son de corridas que se cortaron en el medio: no sirven para
    restaurar (estan incompletos) y nadie los va a mirar nunca.

    El orden por nombre alcanza porque la fecha va en ISO: `stock_2026-08-13`
    ordena igual alfabeticamente que cronologicamente.
    """
    if not CARPETA.exists():
        return

    for huerfano in CARPETA.glob("*.tmp"):
        try:
            huerfano.unlink()
        except OSError:
            pass

    copias = sorted(CARPETA.glob("stock_*.db"))
    for vieja in copias[:-CUANTOS_GUARDAR]:
        try:
            vieja.unlink()
        except OSError:
            pass
