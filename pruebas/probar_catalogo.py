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
                        Operacion, HistorialCatalogo)

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
    # El historial va tambien: si queda un paso de otro escenario, el
    # "deshacer" de este restaura un catalogo que no es el suyo.
    for modelo in (Operacion, AliasPlataforma, EstadoItem, Producto,
                   HistorialCatalogo):
        db.query(modelo).delete()
    from app.models import Preferencia
    db.query(Preferencia).delete()
    db.commit()


# ---------------------------------------------------------------- escenarios

def base_vieja_gana_columnas(db):
    """Una base creada por una version anterior tiene que seguir andando.

    create_all() no toca las tablas que ya existen: sin la migracion, una
    columna nueva del modelo no aparece nunca y TODAS las consultas del
    producto empiezan a fallar con "no such column". La unica salida seria
    borrarle la base al usuario, con su historial adentro.
    """
    print("\n== Base de una version anterior: se le agregan las columnas ==")
    from sqlalchemy import text
    from app.database import engine, init_db

    with engine.begin() as con:
        con.execute(text("DROP TABLE IF EXISTS productos"))
        # El esquema tal como era antes de 'pausado'.
        con.execute(text("""
            CREATE TABLE productos (
                id INTEGER NOT NULL PRIMARY KEY,
                nombre VARCHAR(120) NOT NULL UNIQUE,
                categoria VARCHAR(60),
                orden INTEGER,
                activo BOOLEAN,
                es_plato_del_dia BOOLEAN,
                fecha_dia VARCHAR(10)
            )"""))
        con.execute(text("INSERT INTO productos (nombre, categoria, activo) "
                         "VALUES ('Producto de antes', 'Platos', 1)"))

    init_db()
    db.expire_all()

    p = db.query(Producto).filter_by(nombre="Producto de antes").first()
    revisar(p is not None, "los productos que ya estaban siguen ahi")
    revisar(p is not None and not p.pausado,
            "la columna nueva existe y arranca en falso")

    # Y tiene que poder correrse dos veces sin romper.
    init_db()
    revisar(True, "correr la migracion de nuevo no rompe nada")


def base_recien_creada(db):
    print("\n== Base nueva: el catalogo se siembra como manda seed.py ==")
    limpiar(db)
    seed.sembrar()

    revisar(remotos(db, "Wrap caesar con batatas") ==
            {"pedidosya": "Wrap caesar con batatas", "rappi": None},
            "'Wrap caesar con batatas' queda solo en PedidosYa")

    revisar(remotos(db, "Wrap caesar con ensalada") ==
            {"pedidosya": None, "rappi": "Wrap caesar con ensalada"},
            "'Wrap caesar con ensalada' queda solo en Rappi")

    revisar(remotos(db, "Brie") ==
            {"pedidosya": "Brie", "rappi": "Ensalada Brie"},
            "'Brie' sigue vinculado a 'Ensalada Brie'")


def base_vieja_se_corrige(db):
    print("\n== Base ya sembrada con el mapeo viejo: el arranque lo corrige ==")
    limpiar(db)

    # Asi estaba la base del usuario hasta hoy: los dos wraps vinculados.
    p = Producto(nombre="Wrap caesar con batatas", categoria="Wraps")
    db.add(p)
    db.flush()
    db.add(AliasPlataforma(producto_id=p.id, plataforma="rappi",
                           nombre_remoto="Wrap caesar con ensalada"))
    for plat in ("pedidosya", "rappi"):
        db.add(EstadoItem(producto_id=p.id, plataforma=plat,
                          estado=EstadoItem.APAGADO_HOY))
    db.commit()

    seed.sembrar()
    db.expire_all()

    revisar(remotos(db, "Wrap caesar con batatas") ==
            {"pedidosya": "Wrap caesar con batatas", "rappi": None},
            "se le saca el alias de Rappi al arrancar")

    revisar(remotos(db, "Wrap caesar con ensalada") ==
            {"pedidosya": None, "rappi": "Wrap caesar con ensalada"},
            "el de Rappi aparece como producto propio")


def vincular_y_separar(db):
    print("\n== Vincular y separar desde la app ==")
    limpiar(db)
    seed.sembrar()
    db.expire_all()

    # Dos productos sueltos, uno por plataforma, como los deja la carta
    # cuando el emparejamiento no es seguro.
    catalogo.agregar(db, "rappi", "Bowl Huerta", categoria="Platos")
    db.commit()
    revisar(remotos(db, "Bowl Huerta") ==
            {"pedidosya": None, "rappi": "Bowl Huerta"},
            "agregar() carga un producto de una sola plataforma")

    # Vincular los dos wraps caesar que el usuario dijo que NO van juntos,
    # para despues separarlos: es el ida y vuelta que tiene que aguantar.
    producto = catalogo.vincular(db, "Wrap caesar con batatas",
                                 "Wrap caesar con ensalada")
    db.commit()
    db.expire_all()

    revisar(remotos(db, producto.nombre) ==
            {"pedidosya": "Wrap caesar con batatas",
             "rappi": "Wrap caesar con ensalada"},
            "vincular() fusiona los dos productos sueltos en uno")

    revisar(db.query(Producto).filter_by(nombre="Wrap caesar con ensalada")
            .first() is None,
            "el producto absorbido desaparece de la lista")

    revisar(catalogo.es_manual(db), "el catalogo queda marcado como manual")

    # Y ahora al reves.
    nuevo = catalogo.separar(db, producto.id, "rappi")
    db.commit()
    db.expire_all()

    revisar(remotos(db, "Wrap caesar con batatas") ==
            {"pedidosya": "Wrap caesar con batatas", "rappi": None},
            "separar() deja el de PedidosYa solo")
    revisar(remotos(db, nuevo.nombre) ==
            {"pedidosya": None, "rappi": "Wrap caesar con ensalada"},
            "separar() devuelve el de Rappi como producto propio")


def separar_conserva_el_estado(db):
    print("\n== Separar no pierde el estado real del portal ==")
    limpiar(db)
    seed.sembrar()
    db.expire_all()

    p = db.query(Producto).filter_by(nombre="Brie").first()
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

    absorbido = catalogo.agregar(db, "rappi", "Pollo al Curry")
    db.commit()
    db.add(Operacion(producto_id=absorbido.id, plataforma="rappi",
                     accion="apagar_hoy"))
    db.commit()

    destino = catalogo.vincular(db, "Cobb", "Pollo al Curry")
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

    # El usuario decide que el Risotto de Rappi es otra cosa.
    p = db.query(Producto).filter_by(nombre="Risotto").first()
    catalogo.separar(db, p.id, "rappi")
    db.commit()
    db.expire_all()

    revisar(remotos(db, "Risotto") == {"pedidosya": "Risotto", "rappi": None},
            "queda separado")

    # Un reinicio no tiene que deshacerlo.
    seed.sembrar()
    db.expire_all()
    revisar(remotos(db, "Risotto") == {"pedidosya": "Risotto", "rappi": None},
            "sigue separado despues de reiniciar la app")


def no_se_puede_separar_lo_que_no_esta(db):
    print("\n== Errores tratados como errores ==")
    limpiar(db)
    seed.sembrar()
    db.expire_all()

    solo_rappi = db.query(Producto).filter_by(nombre="Wrap de atun").first()
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


def vincular_no_pisa_lo_que_ya_estaba(db):
    """Vincular a mano dos que ya estaban emparejados con otra cosa.

    El caso que lo pidio: "wrap caesar con batatas" (PedidosYa) es en
    realidad el "wrap caesar" de Rappi. Pero ese ya estaba vinculado con el
    "Wrap caesar" de PedidosYa. Ese ultimo NO se puede evaporar.
    """
    print("\n== Vincular a mano no hace desaparecer al que estaba ==")
    limpiar(db)
    seed.sembrar()
    db.expire_all()

    revisar(remotos(db, "Wrap caesar") ==
            {"pedidosya": "Wrap caesar", "rappi": "Wrap caesar"},
            "de entrada, 'Wrap caesar' esta vinculado con el de Rappi")

    catalogo.vincular(db, "Wrap caesar con batatas", "Wrap caesar")
    db.commit()
    db.expire_all()

    revisar(remotos(db, "Wrap caesar con batatas") ==
            {"pedidosya": "Wrap caesar con batatas", "rappi": "Wrap caesar"},
            "el par nuevo queda vinculado")

    sueltos = [p for p in db.query(Producto).all()
               if catalogo.nombre_remoto(p, "pedidosya") == "Wrap caesar"]
    revisar(len(sueltos) == 1,
            "el 'Wrap caesar' de PedidosYa sigue existiendo, ahora suelto")
    revisar(len(sueltos) == 1 and
            catalogo.nombre_remoto(sueltos[0], "rappi") is None,
            "y quedo sin plataforma de Rappi, no vinculado a la fuerza")


def deshacer_vuelve_atras(db):
    """El caso real del 2026-07-28: tres vinculaciones y un lio.

    Vincular toca varios productos a la vez (suelta al que estaba
    emparejado), asi que revertirlo a mano es un rompecabezas. Deshacer
    tiene que devolver TODO como estaba.
    """
    print("\n== Deshacer ==")
    limpiar(db)
    seed.sembrar()
    db.expire_all()

    antes_caesar = remotos(db, "Wrap caesar")
    cuantos = db.query(Producto).count()

    revisar(catalogo.hay_para_deshacer(db) is None,
            "recien sembrado no hay nada para deshacer")

    catalogo.vincular(db, "Wrap caesar con batatas", "Wrap caesar")
    db.commit()
    db.expire_all()

    revisar(remotos(db, "Wrap caesar con batatas") ==
            {"pedidosya": "Wrap caesar con batatas", "rappi": "Wrap caesar"},
            "la vinculacion se hizo")
    revisar(remotos(db, "Wrap caesar (PedidosYa)") ==
            {"pedidosya": "Wrap caesar", "rappi": None},
            "el de PedidosYa que se solto queda con un nombre que se entiende")
    revisar(db.query(Producto).count() == cuantos,
            "la cuenta no cambia: uno se solto y el otro se absorbio")

    pendiente = catalogo.hay_para_deshacer(db)
    revisar(pendiente is not None and "Wrap caesar" in pendiente,
            f"queda anotado que se puede deshacer ({pendiente})")

    catalogo.deshacer(db)
    db.commit()
    db.expire_all()

    revisar(remotos(db, "Wrap caesar") == antes_caesar,
            "deshacer devuelve el vinculo original")
    revisar(db.query(Producto).filter_by(nombre="Wrap caesar (PedidosYa)")
            .first() is None,
            "y se lleva el producto suelto que habia aparecido")
    revisar(catalogo.hay_para_deshacer(db) is None,
            "no queda nada mas para deshacer")


def deshacer_varios_pasos(db):
    print("\n== Deshacer varios pasos, en orden ==")
    limpiar(db)
    seed.sembrar()
    db.expire_all()

    catalogo.agregar(db, "rappi", "Pollo al Curry")
    db.commit()
    catalogo.agregar(db, "rappi", "Bowl Huerta")
    db.commit()
    db.expire_all()

    revisar(remotos(db, "Bowl Huerta") is not None and
            remotos(db, "Pollo al Curry") is not None,
            "los dos productos estan cargados")

    catalogo.deshacer(db)
    db.commit()
    db.expire_all()
    revisar(remotos(db, "Bowl Huerta") is None and
            remotos(db, "Pollo al Curry") is not None,
            "el primer deshacer saca solo el ultimo")

    catalogo.deshacer(db)
    db.commit()
    db.expire_all()
    revisar(remotos(db, "Pollo al Curry") is None,
            "el segundo saca el anterior")

    revisar(catalogo.deshacer(db) is None,
            "y despues ya no hay nada que deshacer")


def nombres_de_los_sueltos(db):
    """El sobrante tiene que decir de que portal es, no llamarse "(2)"."""
    print("\n== Nombre del producto que queda suelto ==")
    limpiar(db)
    seed.sembrar()
    db.expire_all()

    # "Wrap caesar" se llama igual en los dos portales: al separarlos, uno
    # de los dos productos necesita otro nombre a la fuerza.
    p = db.query(Producto).filter_by(nombre="Wrap caesar").first()
    nuevo = catalogo.separar(db, p.id, "pedidosya")
    db.commit()

    revisar(nuevo.nombre == "Wrap caesar (PedidosYa)",
            f"se llama '{nuevo.nombre}' y no 'Wrap caesar (2)'")


def main():
    init_db()
    db = SessionLocal()
    try:
        base_vieja_gana_columnas(db)
        base_recien_creada(db)
        base_vieja_se_corrige(db)
        vincular_y_separar(db)
        separar_conserva_el_estado(db)
        vincular_remapea_la_cola(db)
        seed_no_pisa_lo_manual(db)
        vincular_no_pisa_lo_que_ya_estaba(db)
        no_se_puede_separar_lo_que_no_esta(db)
        deshacer_vuelve_atras(db)
        deshacer_varios_pasos(db)
        nombres_de_los_sueltos(db)
    finally:
        db.close()
        shutil.rmtree(TEMPORAL, ignore_errors=True)

    print("\n" + ("TODO OK" if not fallos else f"{len(fallos)} FALLAS: {fallos}"))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
