"""Prueba «Apagar todo» y los Ajustes. Sin navegador ni portales.

    py pruebas/probar_cierre.py

Lo delicado de apagar la carta entera no es apagarla: es NO encolar de mas.
Cada operacion recarga la pagina del portal, asi que 30 operaciones que no
hacian falta son veinte minutos de navegador para no cambiar nada. Y lo
importante para el usuario es que se pueda hacer UNA plataforma sola.
"""

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TEMPORAL = tempfile.mkdtemp(prefix="todoselector-cierre-")
os.environ["HOME"] = TEMPORAL
os.environ["LOCALAPPDATA"] = TEMPORAL

from app import cierre, config, seed                            # noqa: E402
from app.database import SessionLocal, init_db                  # noqa: E402
from app.models import Producto, EstadoItem, Operacion          # noqa: E402

fallos = []


def revisar(condicion, titulo):
    print(("  OK    " if condicion else "  FALLA ") + titulo)
    if not condicion:
        fallos.append(titulo)


class WorkerFalso:
    """El worker de verdad abre Chrome. Aca solo importa a quien releyo."""

    def __init__(self):
        self.releidas = []

    async def sincronizar_estados(self, plataforma=None, sostener=False):
        self.releidas.append(plataforma)
        return {plataforma: {"leidos": 0, "prendidos": 0, "apagados": 0}}


def poner(db, nombre, valor, plataforma):
    p = db.query(Producto).filter_by(nombre=nombre).first()
    est = next((e for e in p.estados if e.plataforma == plataforma), None)
    if est is not None:
        est.estado = valor
    db.commit()


def todo_prendido(db):
    for est in db.query(EstadoItem).all():
        est.estado = EstadoItem.PRENDIDO
    for p in db.query(Producto).all():
        p.pausado = False
    db.query(Operacion).delete()
    db.commit()


def cola(db, plataforma=None):
    """Los nombres que quedaron encolados, por plataforma."""
    q = db.query(Operacion).filter(
        Operacion.estado.in_([Operacion.PENDIENTE, Operacion.EN_CURSO]))
    if plataforma:
        q = q.filter(Operacion.plataforma == plataforma)
    return {op.producto.nombre for op in q}


async def una_sola_plataforma(db, worker):
    """Lo que pidio el usuario: apagar PedidosYa sin tocar Rappi."""
    print("\n== Apagar una sola plataforma ==")
    todo_prendido(db)

    resultado = await cierre.ejecutar(worker, "apagar_hoy", ["pedidosya"],
                                      releer=False)
    db.expire_all()

    revisar(resultado["pedidosya"]["total"] > 5,
            f"encola la carta de PedidosYa ({resultado['pedidosya']['total']})")
    revisar("rappi" not in resultado, "y no dice nada de Rappi")
    revisar(len(cola(db, "rappi")) == 0,
            "Rappi queda intacto: ni una operacion encolada")

    # Todo lo encolado tiene que existir en PedidosYa: si el producto es
    # exclusivo de Rappi, buscarlo alla es una operacion que nace fallada.
    from app.catalogo import nombre_remoto
    encolados = [op.producto for op in db.query(Operacion).all()]
    revisar(all(nombre_remoto(p, "pedidosya") is not None for p in encolados),
            "no encola productos que no existen en PedidosYa")

    # Y despues Rappi, que es el orden que el usuario necesita.
    await cierre.ejecutar(worker, "apagar_hoy", ["rappi"], releer=False)
    db.expire_all()
    revisar(len(cola(db, "rappi")) > 5, "y despues se puede encolar Rappi")


async def no_encola_de_mas(db, worker):
    print("\n== No encola lo que no hace falta ==")
    todo_prendido(db)

    poner(db, "Flan casero", EstadoItem.APAGADO_HOY, "rappi")
    poner(db, "Budín de pan", EstadoItem.APAGADO_AJENO, "rappi")
    p = db.query(Producto).filter_by(nombre="Tarta de choclo").first()
    p.pausado = True
    db.commit()

    await cierre.ejecutar(worker, "apagar_hoy", ["rappi"], releer=False)
    db.expire_all()
    encolados = cola(db, "rappi")

    revisar("Flan casero" not in encolados, "saltea lo que la app ya tenia apagado")
    revisar("Budín de pan" not in encolados, "saltea lo que esta apagado desde afuera")
    revisar("Tarta de choclo" not in encolados, "saltea lo que esta en pausa")
    revisar("Milanesa con pure" in encolados, "y encola lo que si esta prendido")

    # Segunda pasada: nada nuevo. Es el doble click sobre "Apagar todo".
    cuantas = db.query(Operacion).count()
    await cierre.ejecutar(worker, "apagar_hoy", ["rappi"], releer=False)
    db.expire_all()
    revisar(db.query(Operacion).count() == cuantas,
            "apretarlo dos veces no duplica la cola")


async def prender_todo(db, worker):
    print("\n== Prender todo ==")
    todo_prendido(db)
    poner(db, "Flan casero", EstadoItem.APAGADO_HOY, "rappi")
    poner(db, "Budín de pan", EstadoItem.APAGADO_AJENO, "rappi")

    await cierre.ejecutar(worker, "prender", ["rappi"], releer=False,
                          solo_propios=True)
    db.expire_all()
    encolados = cola(db, "rappi")

    revisar(encolados == {"Flan casero"},
            f"solo prende lo que apago la app (encolo: {encolados or 'nada'})")

    # De cero otra vez: la pasada anterior dejo a Flan casero en "prendiendo…", y
    # eso lo saltea con razon (ya hay una operacion en curso).
    todo_prendido(db)
    poner(db, "Flan casero", EstadoItem.APAGADO_HOY, "rappi")
    poner(db, "Budín de pan", EstadoItem.APAGADO_AJENO, "rappi")

    await cierre.ejecutar(worker, "prender", ["rappi"], releer=False,
                          solo_propios=False)
    db.expire_all()
    revisar(cola(db, "rappi") == {"Flan casero", "Budín de pan"},
            "y con la opcion en off prende tambien lo apagado desde afuera")


async def estado_transitorio(db, worker):
    print("\n== La pantalla se entera enseguida ==")
    todo_prendido(db)
    await cierre.ejecutar(worker, "apagar_hoy", ["rappi"], releer=False)
    db.expire_all()

    p = db.query(Producto).filter_by(nombre="Flan casero").first()
    est = next(e for e in p.estados if e.plataforma == "rappi")
    revisar(est.estado == EstadoItem.APAGANDO,
            "los productos encolados quedan en 'apagando…' sin esperar al worker")


async def releer_antes(db, worker):
    print("\n== Releer el portal antes de decidir ==")
    todo_prendido(db)
    worker.releidas.clear()

    await cierre.ejecutar(worker, "apagar_hoy", ["rappi"], releer=True)
    revisar(worker.releidas == ["rappi"],
            "con releer=True lee esa plataforma y solo esa")

    worker.releidas.clear()
    db.query(Operacion).delete()
    db.commit()
    await cierre.ejecutar(worker, "apagar_hoy", ["rappi"], releer=False)
    revisar(worker.releidas == [], "con releer=False no toca el navegador")


async def previo(db, worker):
    print("\n== El aviso de cuantos va a tocar ==")
    todo_prendido(db)

    cuentas = cierre.previo(["pedidosya", "rappi"], "apagar_hoy")
    revisar(cuentas["rappi"] > 5 and cuentas["pedidosya"] > 5,
            f"cuenta los dos portales por separado ({cuentas})")

    await cierre.ejecutar(worker, "apagar_hoy", ["rappi"], releer=False)
    db.expire_all()
    revisar(cierre.previo(["rappi"], "apagar_hoy")["rappi"] == 0,
            "una vez encolados, ya no queda nada para apagar")


def ajustes(db):
    print("\n== Ajustes ==")
    revisar(config.entero("minutos_ronda") == 15,
            "sin nada guardado valen los defaults de siempre")

    config.guardar(db, {"minutos_ronda": 30, "sostener_apagados": False,
                        "cierre_accion": "apagar_indef"})
    db.commit()
    config.recargar()

    revisar(config.entero("minutos_ronda") == 30, "guarda un numero")
    revisar(config.activo("sostener_apagados") is False, "guarda un booleano")
    revisar(config.obtener("cierre_accion") == "apagar_indef",
            "guarda una eleccion")

    for cambio, que in [({"minutos_ronda": 9999}, "un numero fuera de rango"),
                        ({"minutos_ronda": "hola"}, "un numero que no es numero"),
                        ({"cierre_accion": "borrar_todo"}, "una eleccion invalida"),
                        ({"rappi_store_id": "a b/c"}, "un id con basura"),
                        ({"no_existe": 1}, "una clave que no existe")]:
        try:
            config.guardar(db, cambio)
            revisar(False, f"rechaza {que}")
        except ValueError:
            revisar(True, f"rechaza {que}")
    db.rollback()

    # Una tanda con un valor malo no tiene que guardar los buenos: quedaria
    # media configuracion aplicada y sin forma de saber cual.
    config.recargar()
    try:
        config.guardar(db, {"max_intentos": 5, "minutos_ronda": 9999})
    except ValueError:
        pass
    db.rollback()
    config.recargar()
    revisar(config.entero("max_intentos") == 3,
            "si una tanda tiene un valor malo no se guarda ninguno")

    config.restablecer(db)
    db.commit()
    config.recargar()
    revisar(config.entero("minutos_ronda") == 15 and
            config.activo("sostener_apagados") is True,
            "restablecer los vuelve a los valores por defecto")


def sucursal_configurable(db):
    """El id de menu y el storeId dejaron de estar clavados en el codigo."""
    print("\n== La sucursal sale de los ajustes ==")
    from plataformas.pedidosya import PedidosYa
    from plataformas.rappi import Rappi

    py = PedidosYa(None, menu_id="999111")
    revisar(py.url_menu.endswith("/999111"),
            f"PedidosYa arma la URL con el menu que le pasan ({py.url_menu})")

    rappi = Rappi(None, store_id="AR000001", brand_id="AR000002")
    revisar("storeId=AR000001" in rappi.url_menu and
            "brandId=AR000002" in rappi.url_menu,
            "Rappi arma la URL con la tienda y la marca que le pasan")

    # Los defaults tienen que seguir siendo los del local de siempre.
    revisar(PedidosYa(None).url_menu.endswith("/MENU_ID") and
            "storeId=STORE_ID" in Rappi(None).url_menu,
            "sin configurar nada, siguen siendo los del local de siempre")

    py.configurar(menu_id="222333")
    revisar(py.url_menu.endswith("/222333"),
            "cambiar de menu no necesita reiniciar la app")

    py._categoria_de["Budín de pan"] = 2
    py.configurar(menu_id="444555")
    revisar(py._categoria_de == {},
            "y olvida en que categoria vivia cada producto: es otro menu")


async def sesion_caida(db):
    """EL BUG DEL 2026-07-28: Rappi se deslogueo y se perdio lo encolado.

    El usuario apago la Flan casero, Rappi estaba deslogueado, le salto el error y
    tuvo que loguearse a mano. Para cuando termino, la operacion ya se habia
    muerto: tres reintentos de 2 segundos contra una sesion que solo vuelve
    con un login manual, y despues ERROR. Lo que habia pedido se perdio en
    silencio.

    Ahora la operacion espera ahi, sin gastar intentos, y sale sola apenas
    vuelve la sesion.
    """
    print("\n== Sesion caida: la operacion espera, no se pierde ==")
    from app.worker import Worker, SIN_SESION

    todo_prendido(db)
    w = Worker()
    w.modo_simulado = False
    w.corriendo = True

    intentos = []

    async def falla_sin_sesion(plataforma, accion, nombre_remoto):
        intentos.append(plataforma)
        w.sesion_ok[plataforma] = False
        return False, "sesion caida: logueate en la ventana del navegador", SIN_SESION

    w._ejecutar = falla_sin_sesion

    p = db.query(Producto).filter_by(nombre="Flan casero").first()
    db.add(Operacion(producto_id=p.id, plataforma="rappi", accion="apagar_hoy"))
    db.commit()

    for _ in range(4):
        await w._procesar_pendientes()

    db.expire_all()
    op = db.query(Operacion).filter_by(producto_id=p.id).first()

    revisar(op.estado == Operacion.PENDIENTE,
            f"la operacion sigue encolada y no en error (quedo: {op.estado})")
    revisar(op.intentos == 0, f"no gasta intentos (lleva {op.intentos})")
    revisar(len(intentos) == 1,
            f"y no machaca la plataforma deslogueada ({len(intentos)} intento)")
    revisar("rappi" in w.reintentar_desde, "queda anotada la espera")

    # Otra plataforma no tiene por que quedarse esperando por esta.
    otro = db.query(Producto).filter_by(nombre="Budín de pan").first()
    db.add(Operacion(producto_id=otro.id, plataforma="pedidosya",
                     accion="apagar_hoy"))
    db.commit()

    hechas = []

    async def anda_bien(plataforma, accion, nombre_remoto):
        hechas.append(plataforma)
        return True, "", ""

    w._ejecutar = anda_bien
    await w._procesar_pendientes()
    revisar(hechas == ["pedidosya"],
            f"PedidosYa sigue trabajando igual ({hechas})")

    # Y al revalidar la sesion, lo que estaba esperando sale enseguida.
    w.reintentar_desde.pop("rappi", None)
    await w._procesar_pendientes()
    db.expire_all()
    op = db.query(Operacion).filter_by(producto_id=p.id).first()
    revisar("rappi" in hechas and op.estado == Operacion.OK,
            "y cuando vuelve la sesion sale sola, sin volver a pedirla")


async def main():
    init_db()
    seed.sembrar()
    config.recargar()

    db = SessionLocal()
    worker = WorkerFalso()
    try:
        await una_sola_plataforma(db, worker)
        await no_encola_de_mas(db, worker)
        await prender_todo(db, worker)
        await estado_transitorio(db, worker)
        await releer_antes(db, worker)
        await previo(db, worker)
        await sesion_caida(db)
        ajustes(db)
        sucursal_configurable(db)
    finally:
        db.close()

    shutil.rmtree(TEMPORAL, ignore_errors=True)
    print("\n" + ("TODO OK" if not fallos else f"{len(fallos)} FALLAS: {fallos}"))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
