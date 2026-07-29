"""Prueba que la lectura del estado real se guarde bien. Sin navegador.

    py pruebas/probar_estados.py

Lo delicado no es leer el portal sino que se vuelca a la base: no pisar una
operacion en curso, no apropiarse de lo que apago el local por su cuenta, y
respetar el tipo de apagado que eligio el usuario.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

TEMPORAL = tempfile.mkdtemp(prefix="todoselector-estados-")
os.environ["HOME"] = TEMPORAL
os.environ["LOCALAPPDATA"] = TEMPORAL

from app import catalogo, seed                                          # noqa: E402
import catalogo_ejemplo                                   # noqa: E402
from app.database import SessionLocal, init_db                # noqa: E402
from app.models import Producto, EstadoItem                   # noqa: E402
from app.worker import Worker                                 # noqa: E402

# app/seed.py viene VACIO a proposito: una instalacion nueva no arranca
# con la carta de otro local. Las pruebas siembran una carta inventada.
catalogo_ejemplo.usar_catalogo()

fallos = []


def revisar(condicion, titulo):
    print(("  OK    " if condicion else "  FALLA ") + titulo)
    if not condicion:
        fallos.append(titulo)


def estado_de(db, nombre, plataforma="rappi"):
    p = db.query(Producto).filter_by(nombre=nombre).first()
    if p is None:
        return None
    est = next((e for e in p.estados if e.plataforma == plataforma), None)
    return est.estado if est else None


def poner(db, nombre, valor, plataforma="rappi"):
    p = db.query(Producto).filter_by(nombre=nombre).first()
    est = next(e for e in p.estados if e.plataforma == plataforma)
    est.estado = valor
    db.commit()


def apagado_que_no_se_puede_confirmar(db):
    """EL BUG DEL 2026-07-28: la pantalla decia apagado y el portal vendia.

    El usuario apago un producto, Todo-Selector lo mostro como "apagado hoy", y
    media hora despues entro un pedido de PedidosYa con ese producto.

    El mecanismo: si la lectura de la carta no encuentra el producto (el
    nombre del catalogo no coincide con el del portal, o no se pudo abrir la
    categoria), la app no pisa el estado que tenia. Eso esta bien -una
    lectura mala no deberia borrar lo que sabiamos- pero el efecto era que un
    "apagado" viejo quedaba congelado y la pantalla lo seguia afirmando en
    presente, sin nada que lo delatara.
    """
    print("\n== Un apagado que la app no puede confirmar ==")
    poner(db, "Flan casero", EstadoItem.APAGADO_HOY)
    poner(db, "Budín de pan", EstadoItem.APAGADO_HOY)

    def sellado(nombre):
        p = db.query(Producto).filter_by(nombre=nombre).first()
        return next(e for e in p.estados if e.plataforma == "rappi").verificado_en

    antes_flan, antes_budin = sellado("Flan casero"), sellado("Budín de pan")

    # El portal devuelve a Budín de pan pero NO a Flan casero: es el caso del producto.
    leido = {"Budín de pan": False}
    resultado = Worker._guardar_estados("rappi", leido, sostener=True)
    db.expire_all()

    ciegos = {n["producto"] for n in resultado["no_encontrados"]}
    revisar("Flan casero" in ciegos, "avisa que no encontro el producto en el portal")
    revisar("Budín de pan" not in ciegos, "y no se queja del que si encontro")

    revisar(estado_de(db, "Flan casero") == EstadoItem.APAGADO_HOY,
            "sigue sin pisar el estado: una lectura mala no borra lo que sabiamos")

    # Lo que lo delata es verificado_en: al que no se vio no se le toca, asi
    # que la hora se queda vieja y la pantalla puede decir "no lo confirmo".
    revisar(sellado("Flan casero") == antes_flan,
            "al que el portal no mostro NO se le actualiza la hora")
    revisar(sellado("Budín de pan") != antes_budin and sellado("Budín de pan") is not None,
            "y al que si mostro se le sella la hora de ahora")

    # El dato que la pantalla necesita para poder avisar.
    ciego = next(n for n in resultado["no_encontrados"] if n["producto"] == "Flan casero")
    revisar(ciego["estado"] == EstadoItem.APAGADO_HOY and
            ciego["nombre_remoto"] == "Flan casero",
            "y dice con que nombre lo buscaba, que es lo que hay que corregir")


def sostener_y_pausa(db):
    """Que sostiene la ronda de cada 15 minutos y que no."""
    print("\n== La ronda de 15 min sostiene lo propio y respeta la pausa ==")
    poner(db, "Flan casero", EstadoItem.APAGADO_HOY)
    poner(db, "Budín de pan", EstadoItem.APAGADO_HOY)
    poner(db, "Tarta de choclo", EstadoItem.APAGADO_AJENO)

    # El portal los muestra a los tres disponibles: alguien los prendio.
    leido = {"Flan casero": True, "Budín de pan": True, "Tarta de choclo y queso": True}

    resultado = Worker._guardar_estados("rappi", leido, sostener=True)
    db.expire_all()
    revividos = {r["producto"] for r in resultado["revividos"]}

    revisar(revividos == {"Flan casero", "Budín de pan"},
            f"solo reencola lo que apago la app (revividos: {revividos})")
    revisar(estado_de(db, "Tarta de choclo") == EstadoItem.PRENDIDO,
            "lo apagado desde afuera que aparece prendido se actualiza y ya")
    revisar(estado_de(db, "Flan casero") == EstadoItem.APAGADO_HOY,
            "al que revivio no se le pisa el estado hasta confirmarlo")

    # Ahora con uno en pausa: no se sostiene mas.
    p = db.query(Producto).filter_by(nombre="Budín de pan").first()
    p.pausado = True
    db.commit()

    resultado = Worker._guardar_estados("rappi", leido, sostener=True)
    db.expire_all()
    revividos = {r["producto"] for r in resultado["revividos"]}

    revisar("Budín de pan" not in revividos,
            "un producto en pausa no se reencola aunque lo hubieramos apagado")
    revisar("Flan casero" in revividos, "y el que no esta en pausa se sigue sosteniendo")
    revisar(estado_de(db, "Budín de pan") == EstadoItem.PRENDIDO,
            "al pausado se le actualiza el estado igual: la lectura sale gratis")

    # En el arranque (sostener=False) nunca se reencola: un "apagado por hoy"
    # de ayer ya vencio solo y volver a apagarlo seria repetir lo de ayer.
    poner(db, "Flan casero", EstadoItem.APAGADO_HOY)
    resultado = Worker._guardar_estados("rappi", leido, sostener=False)
    db.expire_all()
    revisar(resultado["revividos"] == [],
            "la lectura del arranque no reencola nada")
    revisar(estado_de(db, "Flan casero") == EstadoItem.PRENDIDO,
            "y ahi si gana el portal")

    p.pausado = False
    db.commit()


def novedades(db):
    print("\n== Avisar cuando algo aparece en un portal donde no estaba ==")

    # El caso real: la Locro estaba cargada como exclusiva de Rappi y el
    # usuario la agrego a la carta de PedidosYa. En el portal lleva tildes;
    # el nombre canonico del catalogo no.
    leido_py = {
        "Locro del sábado": True,
        "Tarta de choclo": True,
    }
    encontradas = catalogo.detectar_novedades(db, "pedidosya", leido_py)

    revisar(len(encontradas) == 1,
            f"detecta la Locro y nada mas (detecto {len(encontradas)})")
    if encontradas:
        n = encontradas[0]
        revisar(n["producto"] == "Locro del sabado",
                "la relaciona con el producto del catalogo pese a las tildes")
        revisar(n["pedidosya"] == "Locro del sábado" and
                n["rappi"] == "Locro del sábado",
                "arma bien los dos nombres para vincular")

    # Lo que NO tiene que avisar: el tarta de verdura. "Tarta de verdura chica"
    # esta solo en PedidosYa, y en Rappi hay "individual" y "en porcion",
    # que el usuario confirmo que son platos distintos. Da 0.91: alto, pero
    # no identico.
    leido_rappi = {
        "Tarta de verdura individual": True,
        "Tarta de verdura porción": True,
    }
    encontradas = catalogo.detectar_novedades(db, "rappi", leido_rappi)
    revisar(not any(n["producto"] == "Tarta de verdura chica" for n in encontradas),
            "NO propone vincular el tarta de verdura con la version 'individual'")

    # Y los ~18 de Rappi que el usuario decidio no cargar tampoco son aviso.
    encontradas = catalogo.detectar_novedades(
        db, "rappi", {"Wok de vegetales": True, "Guiso de garbanzos": True})
    revisar(encontradas == [],
            "los productos que no estan en el catalogo no generan aviso")

    print("\n== 'No, es otro' no vuelve a preguntar ==")
    catalogo.ignorar_novedad(db, "pedidosya", "Locro del sábado")
    db.commit()
    encontradas = catalogo.detectar_novedades(db, "pedidosya", leido_py)
    revisar(encontradas == [], "una vez ignorada, no vuelve a aparecer")


def main():
    init_db()
    db = SessionLocal()
    try:
        seed.sembrar()
        db.expire_all()

        print("\n== La lectura llena lo que estaba en desconocido ==")
        revisar(estado_de(db, "Budín de pan") == EstadoItem.DESCONOCIDO,
                "antes de leer, el producto esta en desconocido")

        # Como lo devuelve el portal: los nombres son los de Rappi.
        leido = {
            "Budín de pan": True,
            "Tarta de choclo y queso": False,
            "Flan casero": False,
            "Ensalada mixta de hojas": True,
            "Sopa del día": False,
        }

        # Estados de partida que la lectura tiene que respetar o pisar.
        poner(db, "Flan casero", EstadoItem.APAGADO_HOY)          # lo apago la app
        poner(db, "Sopa del dia", EstadoItem.APAGANDO)             # operacion en vuelo
        poner(db, "Ensalada mixta", EstadoItem.APAGADO_HOY)       # la app lo apago...

        resultado = Worker._guardar_estados("rappi", leido)
        db.expire_all()

        revisar(estado_de(db, "Budín de pan") == EstadoItem.PRENDIDO,
                "un producto disponible queda PRENDIDO")

        revisar(estado_de(db, "Tarta de choclo") == EstadoItem.APAGADO_AJENO,
                "uno apagado que la app no apago queda APAGADO_AJENO")

        revisar(estado_de(db, "Flan casero") == EstadoItem.APAGADO_HOY,
                "uno que apago la app conserva 'apagado hoy'")

        revisar(estado_de(db, "Sopa del dia") == EstadoItem.APAGANDO,
                "una operacion en curso no la pisa la lectura")

        revisar(estado_de(db, "Ensalada mixta") == EstadoItem.PRENDIDO,
                "si el portal lo muestra prendido, gana el portal")

        revisar(resultado["prendidos"] == 2 and resultado["apagados"] == 2,
                f"cuenta bien lo leido: {resultado}")
        revisar(resultado["en_curso"] == 1, "cuenta la operacion en vuelo")
        revisar(resultado["no_estan"] > 0,
                "cuenta los del catalogo que el portal no mostro")

        print("\n== Lo que el portal no mostro no se pisa ==")
        antes = estado_de(db, "Budín de pan")
        Worker._guardar_estados("rappi", {"Flan casero": False})
        db.expire_all()
        revisar(estado_de(db, "Budín de pan") == antes,
                "un producto ausente de la lectura conserva lo que sabiamos")

        print("\n== La reverificacion no se apropia de lo ajeno ==")
        # Es el motivo de que APAGADO_AJENO exista: _reverificar() solo
        # reencola lo que figura apagado por la app.
        apagados_que_sostiene = (db.query(EstadoItem)
                                 .filter(EstadoItem.estado.in_(
                                     EstadoItem.APAGADOS_PROPIOS))
                                 .all())
        nombres = {e.producto.nombre for e in apagados_que_sostiene}
        revisar("Tarta de choclo" not in nombres,
                "lo apagado desde el portal no entra en la ronda de reverificacion")
        revisar("Flan casero" in nombres,
                "lo que apago la app si entra")

        sostener_y_pausa(db)
        apagado_que_no_se_puede_confirmar(db)
        novedades(db)
    finally:
        db.close()
        shutil.rmtree(TEMPORAL, ignore_errors=True)

    print("\n" + ("TODO OK" if not fallos else f"{len(fallos)} FALLAS: {fallos}"))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
