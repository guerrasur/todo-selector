"""Las DOS tiendas de Rappi: Turbo y Comun. Sin navegador ni portales.

    py pruebas/probar_rappi_sync.py

El problema que cubre (2026-07-29): Rappi Turbo y Rappi Comun son dos
tiendas distintas del mismo local y **no comparten la carta**. Apagar en
una no apaga en la otra, un plato puede estar en una y no en la otra, y
puede llamarse distinto en cada una.

Lo que se prueba, en orden:

  1. El emparejador cruza TRES cartas y no dos, sin cambiar en nada lo que
     hacia con dos.
  2. Entre las dos tiendas de Rappi se exige mas para emparejar solo: son
     del mismo portal, el mismo plato suele estar escrito igual, y una
     diferencia de texto es mas probable que sea otro plato. La trampa
     concreta: "Empanada de carne chica".
  3. El catalogo puede representar un producto con tres botones, con dos, o
     con dos cualesquiera de los tres.
  4. Al apagar manda la seleccion EXPLICITA: lo que elegiste es lo que se
     encola, ni mas ni menos.
  5. Lo que no paso por la pantalla de asociacion no se apaga en la otra
     tienda — y eso se avisa en vez de quedar en silencio.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

TEMPORAL = tempfile.mkdtemp(prefix="todoselector-rappi-")
os.environ["HOME"] = TEMPORAL
os.environ["LOCALAPPDATA"] = TEMPORAL
# Se toca la API: en simulado no hay navegador que abrir.
os.environ["STOCKSWITCH_SIMULADO"] = "1"

import catalogo_ejemplo                                          # noqa: E402
from app import catalogo, cierre, config                         # noqa: E402
from app.carta import emparejar, emparejar_n, resumen            # noqa: E402
from app.database import SessionLocal                            # noqa: E402
from app.models import Producto, EstadoItem, Operacion           # noqa: E402

fallos = []


def revisar(condicion, titulo):
    print(("  OK    " if condicion else "  FALLA ") + titulo)
    if not condicion:
        fallos.append(titulo)


def nombres_de(grupos, **espera):
    """El grupo que tiene ESOS nombres, si alguno."""
    for g in grupos:
        if g.nombres == espera:
            return g
    return None


# ---------------------------------------------------------------- 1 y 2

def emparejar_tres_cartas():
    print("\n== Cruzar las cartas de las tres, no de dos ==")

    cartas = {
        "pedidosya": ["Empanada de carne", "Tarta de verdura", "Flan casero",
                      "Budin de pan", "Tostado de queso"],
        "rappi": ["Empanada de carne", "Tarta de verdura", "Flan casero",
                  "Budín de pan", "Guiso de garbanzos"],
        "rappi_comun": ["Empanada de carne chica", "Tarta de verdura",
                        "Budín de pan", "Tostado de queso"],
    }
    grupos = emparejar_n(cartas)

    tres = nombres_de(grupos, pedidosya="Tarta de verdura",
                      rappi="Tarta de verdura", rappi_comun="Tarta de verdura")
    revisar(tres is not None and tres.seguro,
            "el mismo nombre en las tres queda en un solo grupo, seguro")

    tildes = nombres_de(grupos, pedidosya="Budin de pan",
                        rappi="Budín de pan", rappi_comun="Budín de pan")
    revisar(tildes is not None and tildes.seguro,
            "las tildes no separan: 'Budin' y 'Budín' son el mismo grupo")

    dos = nombres_de(grupos, pedidosya="Flan casero", rappi="Flan casero")
    revisar(dos is not None and dos.seguro,
            "un plato que no esta en la tienda Comun queda con dos, no con tres")

    sin_turbo = nombres_de(grupos, pedidosya="Tostado de queso",
                           rappi_comun="Tostado de queso")
    revisar(sin_turbo is not None and sin_turbo.seguro,
            "y uno que esta en PedidosYa y en Comun pero NO en Turbo, tambien")

    solo_turbo = nombres_de(grupos, rappi="Guiso de garbanzos")
    revisar(solo_turbo is not None and not solo_turbo.seguro,
            "el que existe en una sola tienda queda solo, sin emparejar")

    # LA TRAMPA. "Empanada de carne chica" puntua 0.91 contra "Empanada de
    # carne": entre portales distintos eso alcanza para emparejar solo, y
    # entre dos tiendas del mismo portal NO tiene que alcanzar.
    print("\n== El prefijo entre las dos tiendas de Rappi no se empareja solo ==")
    trampa = nombres_de(grupos, pedidosya="Empanada de carne",
                        rappi="Empanada de carne",
                        rappi_comun="Empanada de carne chica")
    revisar(trampa is not None,
            "la 'Empanada de carne chica' se PROPONE (no se esconde)")
    revisar(trampa is not None and not trampa.seguro,
            "pero queda a confirmar: apagarla sola seria apagar otro plato")

    r = resumen(grupos, list(cartas))
    a_confirmar = [f["nombres"] for f in r["a_confirmar"]]
    revisar(any(f.get("rappi_comun") == "Empanada de carne chica"
                for f in a_confirmar),
            "y sale en «a confirmar», que es donde el usuario la decide")

    # El mismo parecido, pero entre PedidosYa y Rappi, SI se empareja solo:
    # entre portales el mismo plato se llama distinto todo el tiempo.
    entre_portales = emparejar_n({"pedidosya": ["Tarta de choclo"],
                                  "rappi": ["Tarta de choclo y queso"]})
    revisar(entre_portales[0].seguro,
            "entre PedidosYa y Rappi ese mismo parecido si se empareja solo")


def resumen_por_plataforma():
    print("\n== El resumen dice de que plataformas habla ==")
    cartas = {"pedidosya": ["Flan casero"], "rappi": ["Locro del sábado"],
              "rappi_comun": ["Guiso de garbanzos"]}
    r = resumen(emparejar_n(cartas), list(cartas))

    revisar(r["plataformas"] == ["pedidosya", "rappi", "rappi_comun"],
            "trae la lista de plataformas, para que la pantalla arme columnas")
    revisar(r["solo"]["rappi_comun"] == ["Guiso de garbanzos"],
            "y un «solo en...» por cada una, incluida la tienda Comun")
    revisar(r["solo_rappi"] == ["Locro del sábado"],
            "sin dejar de traer las claves viejas (solo_rappi)")


def con_dos_cartas_no_cambia_nada():
    print("\n== Con dos cartas hace exactamente lo de antes ==")
    py = ["Tarta de verdura", "Tarta de choclo", "Agua chica"]
    rp = ["Tarta de verdura", "Tarta de choclo y queso", "Wok de vegetales"]

    r = resumen(emparejar(py, rp))
    revisar(r["emparejados"] == 2, "empareja los dos de siempre")
    revisar(r["solo_pedidosya"] == ["Agua chica"], "y deja el suelto de PedidosYa")
    revisar(r["solo_rappi"] == ["Wok de vegetales"], "y el de Rappi")
    revisar("rappi_comun" not in r["solo"],
            "sin inventar una tercera plataforma que esta instalacion no usa")


# ------------------------------------------------------------------- 3

def catalogo_con_tres(db):
    print("\n== Un producto puede tener tres botones ==")

    producto = catalogo.vincular_varios(db, {
        "pedidosya": "Sopa del dia",
        "rappi": "Sopa del día",
        "rappi_comun": "Sopa del día",
    })
    db.commit()

    revisar(catalogo.nombre_remoto(producto, "rappi_comun") == "Sopa del día",
            "vincular_varios le deja el nombre de la tienda Comun")
    revisar(all(catalogo.nombre_remoto(producto, p) is not None
                for p in ("pedidosya", "rappi", "rappi_comun")),
            "y las tres plataformas quedan colgadas del mismo producto")
    revisar(len([e for e in producto.estados]) == 3,
            "con un EstadoItem por tienda, que es lo que habilita el boton")

    iguales = db.query(Producto).filter_by(nombre="Sopa del dia").count()
    revisar(iguales == 1, "sin duplicar el producto")


def vincular_dos_no_toca_la_tercera(db):
    print("\n== Vincular dos no le inventa la tercera ==")

    producto = catalogo.vincular_varios(db, {"pedidosya": "Pollo al horno",
                                             "rappi": "Pollo al horno"})
    db.commit()

    revisar(catalogo.nombre_remoto(producto, "rappi_comun") is None,
            "queda sin la tienda Comun: no esta en su carta")

    # Y se le puede sumar despues, que es lo que hace la pantalla de
    # asociacion cuando el usuario confirma el vinculo.
    catalogo.enlazar(db, producto.id, "rappi_comun", "Pollo al horno")
    db.commit()
    revisar(catalogo.nombre_remoto(producto, "rappi_comun") == "Pollo al horno",
            "y se le suma despues, sin crear un producto nuevo")


def absorber_no_pierde_la_tienda_comun(db):
    print("\n== Fusionar no borra en silencio la tienda Comun ==")

    # Un producto que ya paso por la pantalla de asociacion y esta vinculado
    # a las dos tiendas de Rappi, pero todavia no a PedidosYa.
    solo_rappi = catalogo.vincular_varios(db, {
        "rappi": "Guiso de garbanzos",
        "rappi_comun": "Guiso de garbanzos"})
    db.commit()
    revisar(catalogo.nombre_remoto(solo_rappi, "rappi_comun") == "Guiso de garbanzos",
            "arranca vinculado en las dos tiendas de Rappi")

    # Ahora el usuario lo vincula con su nombre de PedidosYa. El producto de
    # Rappi se absorbe: la tienda Comun tiene que viajar con el.
    catalogo.agregar(db, "pedidosya", "Guiso casero")
    db.commit()
    fusionado = catalogo.vincular_varios(db, {"pedidosya": "Guiso casero",
                                              "rappi": "Guiso de garbanzos"})
    db.commit()

    revisar(catalogo.nombre_remoto(fusionado, "rappi_comun") == "Guiso de garbanzos",
            "al fusionar con PedidosYa NO se pierde la tienda Comun")
    revisar(catalogo.nombre_remoto(fusionado, "pedidosya") == "Guiso casero",
            "y queda con las tres")
    sobrevivientes = db.query(Producto).filter(
        Producto.nombre.like("Guiso%")).count()
    revisar(sobrevivientes == 1, "sin dejar un producto huerfano dando vueltas")


def separar_la_tienda_comun(db):
    print("\n== Separar la tienda Comun ==")

    producto = catalogo.vincular_varios(db, {
        "pedidosya": "Ensalada mixta",
        "rappi": "Ensalada mixta de hojas",
        "rappi_comun": "Ensalada mixta de hojas"})
    db.commit()
    ident = producto.id

    nuevo = catalogo.separar(db, ident, "rappi_comun")
    db.commit()
    db.expire_all()

    viejo = db.query(Producto).get(ident)
    revisar(catalogo.nombre_remoto(viejo, "rappi_comun") is None,
            "el producto se queda sin la tienda Comun")
    revisar(catalogo.nombre_remoto(viejo, "rappi") == "Ensalada mixta de hojas",
            "y conserva las otras dos")
    revisar(catalogo.nombre_remoto(nuevo, "rappi_comun") == "Ensalada mixta de hojas",
            "lo separado sobrevive como producto propio")

    catalogo.deshacer(db)
    db.commit()
    db.expire_all()
    revisar(catalogo.nombre_remoto(db.query(Producto).get(ident),
                                   "rappi_comun") == "Ensalada mixta de hojas",
            "y deshacer lo vuelve a juntar")


# ---------------------------------------------------------------- 4 y 5

def cola(db, plataforma=None):
    q = db.query(Operacion).filter(
        Operacion.estado.in_([Operacion.PENDIENTE, Operacion.EN_CURSO]))
    if plataforma:
        q = q.filter(Operacion.plataforma == plataforma)
    return {op.producto.nombre for op in q}


def limpiar(db):
    db.query(Operacion).delete()
    for est in db.query(EstadoItem).all():
        est.estado = EstadoItem.PRENDIDO
    for p in db.query(Producto).all():
        p.pausado = False
    db.commit()


def apagar_manda_la_seleccion(db):
    """Lo que elegiste es lo que se apaga. Sin espejos por atras."""
    from app.main import AccionIn, encolar_accion

    print("\n== Al apagar manda lo que elegiste ==")
    limpiar(db)

    producto = db.query(Producto).filter_by(nombre="Sopa del dia").first()

    r = encolar_accion(AccionIn(producto_id=producto.id, accion="apagar_hoy",
                                plataformas=["rappi"]), db)
    revisar(r["encoladas"] == ["rappi"],
            "elegiste solo Turbo: se encola solo Turbo")
    revisar(cola(db, "rappi_comun") == set(),
            "la tienda Comun NO se toca sola: no la elegiste")

    limpiar(db)
    r = encolar_accion(AccionIn(producto_id=producto.id, accion="apagar_hoy",
                                plataformas=["rappi", "rappi_comun"]), db)
    revisar(sorted(r["encoladas"]) == ["rappi", "rappi_comun"],
            "elegiste las dos tiendas de Rappi: se encolan las dos")
    revisar(cola(db, "pedidosya") == set(), "y PedidosYa queda intacto")

    limpiar(db)
    r = encolar_accion(AccionIn(producto_id=producto.id, accion="apagar_hoy",
                                plataformas=["pedidosya", "rappi", "rappi_comun"]), db)
    revisar(len(r["encoladas"]) == 3, "y elegidas las tres, van las tres")


def lo_no_vinculado_no_se_apaga_y_se_avisa(db):
    from app.main import AccionIn, encolar_accion

    print("\n== Lo que no paso por la asociacion no se apaga a ciegas ==")
    limpiar(db)

    # Este NO esta vinculado a la tienda Comun (no paso por la pantalla).
    producto = db.query(Producto).filter_by(nombre="Flan casero").first()
    revisar(catalogo.nombre_remoto(producto, "rappi_comun") is None,
            "el producto no esta vinculado en la tienda Comun")

    r = encolar_accion(AccionIn(producto_id=producto.id, accion="apagar_hoy",
                                plataformas=["rappi", "rappi_comun"]), db)
    revisar(r["encoladas"] == ["rappi"], "se encola Turbo, que si esta")
    salteada = next((s for s in r["salteadas"]
                     if s["plataforma"] == "rappi_comun"), None)
    revisar(salteada is not None,
            "y la tienda Comun se saltea en vez de apagar cualquier cosa")
    revisar(salteada is not None and "no existe" in salteada["motivo"],
            f"diciendo por que ({salteada and salteada['motivo']})")


def avisa_si_quedo_apagado_en_una_sola(db):
    from app.main import alertas

    print("\n== Avisa si quedo apagado en una tienda y prendido en la otra ==")
    limpiar(db)

    producto = db.query(Producto).filter_by(nombre="Sopa del dia").first()
    for est in producto.estados:
        if est.plataforma == "rappi":
            est.estado = EstadoItem.APAGADO_HOY
    db.commit()

    salida = alertas(db)
    aviso = next((a for a in salida["sin_espejo"]
                  if a["producto"] == "Sopa del dia"), None)
    revisar(aviso is not None,
            "apagado en Turbo y prendido en Comun: sale el aviso")
    revisar(aviso is not None and aviso["prendida_en"] == "rappi_comun",
            "y dice en cual quedo prendido, que es donde se sigue vendiendo")

    # Apagado en las dos: no hay nada que avisar.
    for est in producto.estados:
        if est.plataforma == "rappi_comun":
            est.estado = EstadoItem.APAGADO_HOY
    db.commit()
    salida = alertas(db)
    revisar(not any(a["producto"] == "Sopa del dia"
                    for a in salida["sin_espejo"]),
            "apagado en las dos: no molesta con un aviso")

    # Un producto que ni siquiera esta en la tienda Comun no puede alertar
    # para siempre: puede que ahi no se venda, y eso se resuelve en la
    # pantalla de asociacion (por el aviso de novedad), no con un cartel fijo.
    flan = db.query(Producto).filter_by(nombre="Flan casero").first()
    for est in flan.estados:
        if est.plataforma == "rappi":
            est.estado = EstadoItem.APAGADO_HOY
    db.commit()
    revisar(not any(a["producto"] == "Flan casero"
                    for a in alertas(db)["sin_espejo"]),
            "y el que no existe en la otra tienda no genera ruido permanente")


async def apagar_todo_por_combinacion(db):
    print("\n== «Apagar todo» sobre las combinaciones que se pidieron ==")

    class WorkerFalso:
        async def sincronizar_estados(self, plataforma=None, sostener=False):
            return {plataforma: {"leidos": 0}}

    worker = WorkerFalso()

    limpiar(db)
    await cierre.ejecutar(worker, "apagar_hoy", ["rappi_comun"], releer=False)
    db.expire_all()
    revisar(len(cola(db, "rappi_comun")) > 0, "se puede apagar SOLO la tienda Comun")
    revisar(cola(db, "rappi") == set() and cola(db, "pedidosya") == set(),
            "sin tocar Turbo ni PedidosYa")

    limpiar(db)
    resultado = await cierre.ejecutar(worker, "apagar_hoy",
                                      ["rappi", "rappi_comun"], releer=False)
    db.expire_all()
    revisar(set(resultado) == {"rappi", "rappi_comun"},
            "se pueden apagar las dos tiendas de Rappi juntas")
    revisar(cola(db, "pedidosya") == set(), "y PedidosYa sigue intacto")

    limpiar(db)
    resultado = await cierre.ejecutar(
        worker, "apagar_hoy", ["pedidosya", "rappi", "rappi_comun"], releer=False)
    db.expire_all()
    revisar(len(resultado) == 3, "y las tres de una, que es el cierre del local")

    # Cada tienda encola SUS productos: la carta no es la misma.
    revisar(cola(db, "rappi") != cola(db, "rappi_comun"),
            "cada tienda encola su propia carta, que no es la misma")


def previo_de_cada_combinacion():
    print("\n== El «cuantos toca» de cada combinacion ==")
    previo = cierre.previo(config.plataformas_activas(), "apagar_hoy")
    revisar(set(previo) == {"pedidosya", "rappi", "rappi_comun"},
            "cuenta las tres por separado, que es con lo que la pantalla "
            "arma «solo Turbo», «ambos Rappi» y «las tres»")
    revisar(all(v >= 0 for v in previo.values()), "y son numeros")


# ------------------------------------------------------------------ Main

def main():
    catalogo_ejemplo.preparar()
    from app.seed import sembrar
    sembrar()

    db = SessionLocal()
    try:
        config.guardar(db, {"rappi_comun_store_id":
                            catalogo_ejemplo.STORE_ID_RAPPI_COMUN})
        db.commit()
        config.recargar()
        revisar("rappi_comun" in config.plataformas_activas(),
                "la tienda Comun queda activa para estas pruebas")

        catalogo_ejemplo.vincular_rappi_comun(db)
        db.expire_all()

        emparejar_tres_cartas()
        resumen_por_plataforma()
        con_dos_cartas_no_cambia_nada()

        catalogo_con_tres(db)
        vincular_dos_no_toca_la_tercera(db)
        absorber_no_pierde_la_tienda_comun(db)
        separar_la_tienda_comun(db)

        apagar_manda_la_seleccion(db)
        lo_no_vinculado_no_se_apaga_y_se_avisa(db)
        avisa_si_quedo_apagado_en_una_sola(db)
        asyncio.run(apagar_todo_por_combinacion(db))
        previo_de_cada_combinacion()
    finally:
        db.close()

    print("\n" + ("TODO OK" if not fallos else
                  f"{len(fallos)} FALLAS:\n  - " + "\n  - ".join(fallos)))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
