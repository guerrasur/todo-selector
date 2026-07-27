"""Prueba vincular/separar y la sincronizacion del catalogo. Sin navegador.

    py pruebas/probar_catalogo.py

Corre contra una base SQLite descartable (se apunta HOME a una carpeta
temporal), asi que no toca la base real ni los portales.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# OJO: tiene que estar ANTES de importar app.database, que resuelve la ruta
# de la base al importarse.
TEMPORAL = tempfile.mkdtemp(prefix="todoselector-prueba-")
os.environ["HOME"] = TEMPORAL
os.environ["LOCALAPPDATA"] = TEMPORAL

from app import catalogo, seed                                    # noqa: E402
from app.database import SessionLocal, init_db                    # noqa: E402
from app.models import (Producto, AliasPlataforma, EstadoItem,    # noqa: E402
                        Operacion)

fallos = []


def revisar(condicion, titulo):
    print(("  OK    " if condicion else "  FALLA ") + titulo)
    if not condicion:
        fallos.append(titulo)


def remotos(db, nombre):
    """Como se llama ese producto en cada portal. None = no esta ahi."""
    p = db.query(Producto).filter_by(nombre=nombre).first()
    if p is None:
        return None
    return {plat: catalogo.nombre_remoto(p, plat)
            for plat in catalogo.PLATAFORMAS}


def limpiar(db):
    for modelo in (Operacion, AliasPlataforma, EstadoItem, Producto):
        db.query(modelo).delete()
    from app.models import Preferencia
    db.query(Preferencia).delete()
    db.commit()


# ---------------------------------------------------------------- escenarios

def base_recien_creada(db):
    print("\n== Base nueva: el catalogo se siembra como manda seed.py ==")
    limpiar(db)
    seed.sembrar()

    revisar(remotos(db, "Tarta de verdura chica") ==
            {"pedidosya": "Tarta de verdura chica", "rappi": None},
            "'Tarta de verdura chica' queda solo en PedidosYa")

    revisar(remotos(db, "Tarta de verdura individual") ==
            {"pedidosya": None, "rappi": "Tarta de verdura individual"},
            "'Tarta de verdura individual' queda solo en Rappi")

    revisar(remotos(db, "Budín de pan") ==
            {"pedidosya": "Budín de pan", "rappi": "Budín de pan"},
            "'Budín de pan' sigue vinculado a 'Budín de pan'")


def base_vieja_se_corrige(db):
    print("\n== Base ya sembrada con el mapeo viejo: el arranque lo corrige ==")
    limpiar(db)

    # Asi estaba la base del usuario hasta hoy: los dos tartas vinculados.
    p = Producto(nombre="Tarta de verdura chica", categoria="Tartas")
    db.add(p)
    db.flush()
    db.add(AliasPlataforma(producto_id=p.id, plataforma="rappi",
                           nombre_remoto="Tarta de verdura individual"))
    for plat in ("pedidosya", "rappi"):
        db.add(EstadoItem(producto_id=p.id, plataforma=plat,
                          estado=EstadoItem.APAGADO_HOY))
    db.commit()

    seed.sembrar()
    db.expire_all()

    revisar(remotos(db, "Tarta de verdura chica") ==
            {"pedidosya": "Tarta de verdura chica", "rappi": None},
            "se le saca el alias de Rappi al arrancar")

    revisar(remotos(db, "Tarta de verdura individual") ==
            {"pedidosya": None, "rappi": "Tarta de verdura individual"},
            "el de Rappi aparece como producto propio")


def vincular_y_separar(db):
    print("\n== Vincular y separar desde la app ==")
    limpiar(db)
    seed.sembrar()
    db.expire_all()

    # Dos productos sueltos, uno por plataforma, como los deja la carta
    # cuando el emparejamiento no es seguro.
    catalogo.agregar(db, "rappi", "Guiso de garbanzos", categoria="Platos")
    db.commit()
    revisar(remotos(db, "Guiso de garbanzos") ==
            {"pedidosya": None, "rappi": "Guiso de garbanzos"},
            "agregar() carga un producto de una sola plataforma")

    # Vincular los dos tartas de verdura que el usuario dijo que NO van juntos,
    # para despues separarlos: es el ida y vuelta que tiene que aguantar.
    producto = catalogo.vincular(db, "Tarta de verdura chica",
                                 "Tarta de verdura individual")
    db.commit()
    db.expire_all()

    revisar(remotos(db, producto.nombre) ==
            {"pedidosya": "Tarta de verdura chica",
             "rappi": "Tarta de verdura individual"},
            "vincular() fusiona los dos productos sueltos en uno")

    revisar(db.query(Producto).filter_by(nombre="Tarta de verdura individual")
            .first() is None,
            "el producto absorbido desaparece de la lista")

    revisar(catalogo.es_manual(db), "el catalogo queda marcado como manual")

    # Y ahora al reves.
    nuevo = catalogo.separar(db, producto.id, "rappi")
    db.commit()
    db.expire_all()

    revisar(remotos(db, "Tarta de verdura chica") ==
            {"pedidosya": "Tarta de verdura chica", "rappi": None},
            "separar() deja el de PedidosYa solo")
    revisar(remotos(db, nuevo.nombre) ==
            {"pedidosya": None, "rappi": "Tarta de verdura individual"},
            "separar() devuelve el de Rappi como producto propio")


def separar_conserva_el_estado(db):
    print("\n== Separar no pierde el estado real del portal ==")
    limpiar(db)
    seed.sembrar()
    db.expire_all()

    p = db.query(Producto).filter_by(nombre="Budín de pan").first()
    est = (db.query(EstadoItem)
           .filter_by(producto_id=p.id, plataforma="rappi").first())
    est.estado = EstadoItem.APAGADO_HOY
    est.detalle = "apagado a mano"
    db.commit()

    nuevo = catalogo.separar(db, p.id, "rappi")
    db.commit()
    db.expire_all()

    est_nuevo = (db.query(EstadoItem)
                 .filter_by(producto_id=nuevo.id, plataforma="rappi").first())
    revisar(est_nuevo is not None and est_nuevo.estado == EstadoItem.APAGADO_HOY,
            "el producto separado se lleva el estado que tenia")
    revisar(est_nuevo is not None and est_nuevo.detalle == "apagado a mano",
            "y tambien el detalle")


def vincular_remapea_la_cola(db):
    print("\n== Vincular no deja operaciones huerfanas en la cola ==")
    limpiar(db)
    seed.sembrar()
    db.expire_all()

    absorbido = catalogo.agregar(db, "rappi", "Wok de vegetales")
    db.commit()
    db.add(Operacion(producto_id=absorbido.id, plataforma="rappi",
                     accion="apagar_hoy"))
    db.commit()

    destino = catalogo.vincular(db, "Flan casero", "Wok de vegetales")
    db.commit()
    db.expire_all()

    op = db.query(Operacion).first()
    revisar(op is not None and op.producto_id == destino.id,
            "la operacion en cola apunta al producto que quedo")
    revisar(db.query(Producto).get(absorbido.id) is None,
            "el producto absorbido ya no esta")


def seed_no_pisa_lo_manual(db):
    print("\n== Con catalogo manual, seed.py deja de pisar los alias ==")
    limpiar(db)
    seed.sembrar()
    db.expire_all()

    # El usuario decide que el Ensalada mixta de Rappi es otra cosa.
    p = db.query(Producto).filter_by(nombre="Ensalada mixta").first()
    catalogo.separar(db, p.id, "rappi")
    db.commit()
    db.expire_all()

    revisar(remotos(db, "Ensalada mixta") == {"pedidosya": "Ensalada mixta", "rappi": None},
            "queda separado")

    # Un reinicio no tiene que deshacerlo.
    seed.sembrar()
    db.expire_all()
    revisar(remotos(db, "Ensalada mixta") == {"pedidosya": "Ensalada mixta", "rappi": None},
            "sigue separado despues de reiniciar la app")


def no_se_puede_separar_lo_que_no_esta(db):
    print("\n== Errores tratados como errores ==")
    limpiar(db)
    seed.sembrar()
    db.expire_all()

    solo_rappi = db.query(Producto).filter_by(nombre="Tarta de zapallo").first()
    try:
        catalogo.separar(db, solo_rappi.id, "rappi")
        revisar(False, "separar() rechaza separar un producto de una sola plataforma")
    except ValueError:
        revisar(True, "separar() rechaza separar un producto de una sola plataforma")

    db.rollback()
    try:
        catalogo.separar(db, solo_rappi.id, "pedidosya")
        revisar(False, "separar() rechaza una plataforma donde el producto no esta")
    except ValueError:
        revisar(True, "separar() rechaza una plataforma donde el producto no esta")
    db.rollback()


def main():
    init_db()
    db = SessionLocal()
    try:
        base_recien_creada(db)
        base_vieja_se_corrige(db)
        vincular_y_separar(db)
        separar_conserva_el_estado(db)
        vincular_remapea_la_cola(db)
        seed_no_pisa_lo_manual(db)
        no_se_puede_separar_lo_que_no_esta(db)
    finally:
        db.close()
        shutil.rmtree(TEMPORAL, ignore_errors=True)

    print("\n" + ("TODO OK" if not fallos else f"{len(fallos)} FALLAS: {fallos}"))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
