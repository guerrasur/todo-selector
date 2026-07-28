"""Apagar (o prender) TODA la carta de una plataforma, de un saque.

Es el "botón de apagar todo al cierre" que faltaba, con una vuelta de rosca
que pidió el usuario (2026-07-28):

    "necesitaría una opción para apagar solo de una plataforma si así lo
     requiero (porque a veces PedidosYa tengo que apagarlo antes que Rappi)"

Por eso el destino es una LISTA de plataformas y no las dos siempre: los
botones de la pantalla son «PedidosYa», «Rappi» y «los dos», y la cola se
llena en el orden en que se aprietan.

Lo que NO hace, a propósito:

  - No encola lo que ya figura como quería quedar. Apagar toda la carta son
    ~30 operaciones por portal y cada una recarga la página: saltear las que
    no hacen falta es la diferencia entre un minuto y veinte.
  - No encola dos veces lo mismo. Un doble click sobre "Apagar todo" son 60
    operaciones duplicadas, y cada una vuelve a clickear el toggle.
  - No toca los pausados (salvo que lo pidas en Ajustes): son justamente los
    que el usuario se sacó de encima.
  - "Prender todo" no toca lo que figura `apagado (afuera)` salvo que lo
    pidas: si lo apagó alguien desde el portal, fue a propósito.

La decisión se toma con lo que la app tiene leído. Como eso puede estar
viejo, por defecto se relee el portal antes (ajuste `cierre_releer`).
"""

import logging
from datetime import datetime

from . import config
from .catalogo import PLATAFORMAS, nombre_remoto
from .database import SessionLocal
from .models import Producto, EstadoItem, Operacion

log = logging.getLogger("cierre")

ACCIONES = ("apagar_hoy", "apagar_indef", "prender")


def _motivo_para_saltear(est: EstadoItem, accion: str,
                         solo_propios: bool) -> str | None:
    """Por que este producto no necesita que lo toquemos. None = si hace falta."""
    if est.estado in EstadoItem.EN_CURSO:
        return "ya hay una operación en curso"

    if accion == "prender":
        if est.estado == EstadoItem.PRENDIDO:
            return "ya figura prendido"
        if solo_propios and est.estado == EstadoItem.APAGADO_AJENO:
            return "lo apagaron desde el portal, no la app"
        return None

    # Apagar. FALLO y DESCONOCIDO entran igual: no sabemos como esta, y
    # apagar() relee antes de clickear, asi que en el peor caso no hace nada.
    if est.estado in EstadoItem.APAGADOS_PROPIOS:
        return "ya figura apagado"
    if est.estado == EstadoItem.APAGADO_AJENO:
        return "ya figura apagado (afuera)"
    return None


def planificar(db, plataforma: str, accion: str,
               incluir_pausados: bool, solo_propios: bool) -> dict:
    """Que productos habria que tocar en esa plataforma. No escribe nada."""
    encolar, salteados = [], []

    productos = (db.query(Producto)
                 .filter(Producto.activo == True)      # noqa: E712
                 .order_by(Producto.orden).all())

    # Lo que ya esta en la cola no se vuelve a encolar.
    ya_en_cola = {
        (op.producto_id, op.plataforma)
        for op in db.query(Operacion).filter(
            Operacion.plataforma == plataforma,
            Operacion.estado.in_([Operacion.PENDIENTE, Operacion.EN_CURSO]),
        )
    }

    for p in productos:
        if nombre_remoto(p, plataforma) is None:
            continue                     # no existe en esta plataforma

        if p.pausado and not incluir_pausados:
            salteados.append({"producto": p.nombre, "motivo": "está en pausa"})
            continue

        if (p.id, plataforma) in ya_en_cola:
            salteados.append({"producto": p.nombre,
                              "motivo": "ya estaba encolado"})
            continue

        est = next((e for e in p.estados if e.plataforma == plataforma), None)
        if est is None:
            continue

        motivo = _motivo_para_saltear(est, accion, solo_propios)
        if motivo:
            salteados.append({"producto": p.nombre, "motivo": motivo})
            continue

        encolar.append(p)

    return {"encolar": encolar, "salteados": salteados}


def _encolar(db, productos: list[Producto], plataforma: str,
             accion: str, detalle: str) -> list[str]:
    nombres = []
    for p in productos:
        db.add(Operacion(producto_id=p.id, plataforma=plataforma,
                         accion=accion, detalle=detalle))

        # Igual que en /api/accion: la pantalla tiene que mostrar enseguida
        # que ese producto esta en movimiento, sin esperar al worker.
        est = next((e for e in p.estados if e.plataforma == plataforma), None)
        if est is not None:
            est.estado = (EstadoItem.PRENDIENDO if accion == "prender"
                          else EstadoItem.APAGANDO)
        nombres.append(p.nombre)
    return nombres


async def ejecutar(worker, accion: str, plataformas: list[str],
                   releer: bool | None = None,
                   incluir_pausados: bool | None = None,
                   solo_propios: bool | None = None) -> dict:
    """Encola la carta entera de cada plataforma pedida, en ese orden."""
    if accion not in ACCIONES:
        raise ValueError(f"acción inválida: {accion}")

    objetivo = [p for p in plataformas if p in PLATAFORMAS]
    if not objetivo:
        raise ValueError("no elegiste ninguna plataforma conocida")

    if releer is None:
        releer = config.activo("cierre_releer")
    if incluir_pausados is None:
        incluir_pausados = config.activo("cierre_incluir_pausados")
    if solo_propios is None:
        solo_propios = config.activo("apertura_solo_propios")

    salida = {}
    for plataforma in objetivo:
        leido = None
        if releer:
            # Con la carta recien leida, "ya figura apagado" es verdad y no
            # una suposicion sobre lo que decia la lectura de hace un rato.
            try:
                resultado = await worker.sincronizar_estados(plataforma)
                leido = resultado.get(plataforma)
            except Exception as e:
                log.exception("Releyendo %s antes del cierre", plataforma)
                leido = {"error": " ".join(str(e).split())[:200]}

        db = SessionLocal()
        try:
            plan = planificar(db, plataforma, accion,
                              incluir_pausados, solo_propios)
            nombres = _encolar(db, plan["encolar"], plataforma, accion,
                               f"masivo {accion} "
                               f"{datetime.now().isoformat(timespec='seconds')}")
            db.commit()
        finally:
            db.close()

        salida[plataforma] = {
            "encoladas": nombres,
            "total": len(nombres),
            "salteados": plan["salteados"],
            "lectura": leido,
        }
        log.info("Cierre %s en %s: %s encoladas, %s salteadas",
                 accion, plataforma, len(nombres), len(plan["salteados"]))

    return salida


def previo(plataformas: list[str], accion: str) -> dict:
    """Cuantos tocaria cada plataforma, para poder avisar ANTES de apretar.

    Apagar la carta entera es de las pocas cosas de esta app que no se
    deshacen con un click, asi que la pantalla pregunta primero y para
    preguntar necesita el numero.
    """
    incluir_pausados = config.activo("cierre_incluir_pausados")
    solo_propios = config.activo("apertura_solo_propios")

    db = SessionLocal()
    try:
        return {
            plataforma: len(planificar(db, plataforma, accion,
                                       incluir_pausados,
                                       solo_propios)["encolar"])
            for plataforma in plataformas if plataforma in PLATAFORMAS
        }
    finally:
        db.close()
