"""Carga inicial de productos con sus nombres en cada plataforma.

IMPORTANTE: los nombres difieren mucho entre PedidosYa y Rappi.
Formato: (nombre_canonico, categoria, nombre_en_pedidosya, nombre_en_rappi)
Si un nombre es None, ese producto NO existe en esa plataforma.

REVISAR LAS MARCAS "DUDA" ANTES DE USAR EN PRODUCCION.

Las tildes de los nombres de Rappi salen del portal mismo, via /api/nombres
(2026-07-27). Sin tilde no se encuentran: se buscan con exact=True.

OJO: esta lista esta INCOMPLETA a proposito. El portal de Rappi muestra 45
productos y aca hay 31. El usuario decidio (2026-07-27) NO cargar los ~18
que estan solo en Rappi ni la Mixta: prefiere que la app lea las cartas
y que el vinculo lo decida el desde la pantalla Carta. Ver app/catalogo.py.

Esto es la carga INICIAL, no el catalogo definitivo. En cuanto el usuario
vincula o separa algo desde la app, la base pasa a mandar y este archivo
deja de tocar los alias (ver sembrar()).
"""

import logging

from .catalogo import es_manual
from .database import SessionLocal
from .models import Producto, AliasPlataforma, EstadoItem

log = logging.getLogger("seed")

# (canonico, categoria, pedidosya, rappi)
PRODUCTOS = [
    # ---------------- Platos ----------------
    ("Tarta de choclo", "Platos", "Tarta de choclo", "Tarta de choclo y queso"),
    ("Flan casero", "Platos", "Flan casero", "Flan casero"),
    ("Milanesa con pure", "Platos", "Milanesa con pure", "Milanesa con puré"),
    ("Budín de pan", "Platos", "Budín de pan", "Budín de pan"),
    ("Milanesa napolitana", "Platos", "Milanesa napolitana", "Milanesa napolitana"),
    ("Pollo al horno", "Platos", "Pollo al horno", "Pollo al horno"),
    ("Sopa del dia", "Platos", "Sopa del dia", "Sopa del día"),
    ("Pollo al verdeo", "Platos", "Pollo al verdeo", "Pollo al verdeo"),

    # Mixta: descontinuada, no se usa mas. Se deja comentada por si vuelve.
    # ("Mixta", "Platos", "Mixta", None),

    # CONFIRMADO: "Ñoquis del 29" no existe en PedidosYa.
    ("Ñoquis del 29", "Platos", None, "Ñoquis del 29"),

    # ---------------- Tartas ----------------
    ("Tarta de choclo", "Tartas", "Tarta de choclo", "Tarta de choclo"),
    ("Tarta de verdura", "Tartas", "Tarta de verdura", "Tarta de verdura"),
    ("Tarta de cebolla", "Tartas", "Tarta de cebolla", "Tarta de cebolla"),
    ("Tarta de espinaca", "Tartas",
     "Tarta de espinaca", "Tarta de espinaca"),

    # RESUELTO POR EL USUARIO (2026-07-27): el "Tarta de verdura chica" de
    # PedidosYa NO es ninguno de los dos tartas de verdura con guarnicion de
    # Rappi ("en porcion" y "individual"): son platos distintos. Antes
    # estaban vinculados, asi que apagar uno apagaba el que no era.
    ("Tarta de verdura chica", "Tartas", "Tarta de verdura chica", None),
    ("Tarta de verdura individual", "Tartas", None, "Tarta de verdura individual"),

    # Los otros tres tartas con guarnicion siguen vinculados: el usuario dijo
    # que le es indiferente y que prefiere decidirlo desde la app. Si no son
    # el mismo plato, el boton "Separar" de la pantalla Carta los desarma.
    ("Tarta de zapallo chica", "Tartas",
     "Tarta de zapallo chica", "Tarta de zapallo individual"),
    ("Tarta de cebolla chica", "Tartas",
     "Tarta de cebolla chica", "Tarta de cebolla individual"),
    ("Tarta de espinaca chica", "Tartas",
     "Tarta de espinaca chica", "Tarta de espinaca individual"),

    # CONFIRMADO: "Tarta de zapallo" (sin guarnicion) no existe en PedidosYa.
    ("Tarta de zapallo", "Tartas", None, "Tarta de zapallo"),
    # CONFIRMADO: "Tarta de choclo individual" no existe en PedidosYa.
    ("Tarta de choclo individual", "Tartas", None, "Tarta de choclo individual"),

    # ---------------- Platos ----------------
    # En PedidosYa estos figuran bajo "Platos"; en Rappi bajo "Plato del Dia".
    # Los dejo como categoria propia para que se vean juntos en la UI.
    ("Empanada de carne", "Platos", "Empanada de carne", "Empanada de carne"),
    ("Ensalada mixta", "Platos", "Ensalada mixta", "Ensalada mixta de hojas"),
    ("Tarta de jamon y queso", "Platos", "Tarta de jamon y queso", "Tarta de jamón y queso"),
    ("fideos con salsa", "Platos",
     "fideos con salsa", "fideos con salsa"),
    ("Pollo al horno", "Platos", "Pollo al horno", "Pollo al horno"),
    ("Pollo al horno sin sal", "Platos",
     "Pollo al horno sin sal", "Pollo al horno sin sal"),

    # CONFIRMADO: la Locro no existe en PedidosYa.
    ("Locro del sabado", "Platos",
     None, "Locro del sábado"),

    # ---------------- Bebidas ----------------
    ("Agua chica", "Bebidas", "Agua chica", "Manantial sin gas 500 ml"),
    ("Agua chica con gas", "Bebidas", "Agua chica con gas", "Manantial con gas 500 ml"),
    ("Gaseosa cola", "Bebidas", "Gaseosa cola", "Gaseosa cola 500 ml"),

    # CONFIRMADO: en PedidosYa se cargo mal y quedo "Gaseosa cola cero".
    # El nombre esta asi en el portal, no es un typo de esta lista.
    # CONFIRMADO POR /api/buscar-texto (2026-07-27): en Rappi lleva tilde,
    # "almibar". Los nombres se buscan con exact=True, asi que sin la tilde
    # no lo encontraba.
    ("Gaseosa cola cero", "Bebidas", "Gaseosa cola cero", "Gaseosa cola cero 500 ml"),
]

PLATAFORMAS = ["pedidosya", "rappi"]


def sembrar():
    db = SessionLocal()
    try:
        if db.query(Producto).count() == 0:
            # Recien creada: _crear_todo ya deja los alias como manda el
            # catalogo, y como la sesion es autoflush=False, sincronizar
            # aca no veria lo que acaba de agregarse y los duplicaria.
            _crear_todo(db)
        elif es_manual(db):
            # El usuario vinculo o separo productos desde la app. Desde ese
            # momento manda la base: si siguieramos sincronizando, cada
            # reinicio deshacia sus decisiones.
            log.info("Catalogo manejado desde la app: no toco los alias")
        else:
            _sincronizar(db)
        db.commit()
    finally:
        db.close()


def _sincronizar(db):
    """Corre en cada arranque: el catalogo manda sobre el mapeo de nombres.

    Este proyecto no tiene migraciones. Sin esto, corregir un nombre en
    PRODUCTOS no servia de nada en una base ya sembrada: los alias viejos
    quedaban para siempre y el producto seguia sin encontrarse en el portal.

    Sincroniza en los dos sentidos:
      - agrega o corrige el alias cuando el catalogo trae un nombre
      - lo SACA cuando el catalogo dice None, que es como se escribe "este
        producto no existe en esa plataforma"

    Lo segundo hacia falta para poder desvincular: al marcar el "Tarta de verdura
    chica" como exclusivo de PedidosYa, sin esto la base se quedaba
    con el alias de Rappi y lo seguia apagando alla.
    """
    for canonico, categoria, n_py, n_rappi in PRODUCTOS:
        p = db.query(Producto).filter_by(nombre=canonico).first()
        if p is None:
            p = _crear_producto(db, canonico, categoria, n_py, n_rappi,
                                orden=len(PRODUCTOS))
            log.info("producto nuevo del catalogo: '%s'", canonico)
            continue

        for plataforma, remoto in (("pedidosya", n_py), ("rappi", n_rappi)):
            al = (db.query(AliasPlataforma)
                  .filter_by(producto_id=p.id, plataforma=plataforma).first())

            if not remoto:
                # El catalogo dice que no existe alla: se va el alias y se va
                # el estado, que es lo que hace que la UI muestre el chip "—".
                if al is not None:
                    log.info("alias %s/%s: '%s' -> (ya no existe ahi)",
                             canonico, plataforma, al.nombre_remoto)
                    db.delete(al)
                est = (db.query(EstadoItem)
                       .filter_by(producto_id=p.id, plataforma=plataforma).first())
                if est is not None:
                    db.delete(est)
                continue

            # Existe en esa plataforma: nos aseguramos de que tenga estado.
            if not any(e.plataforma == plataforma for e in p.estados):
                db.add(EstadoItem(producto_id=p.id, plataforma=plataforma,
                                  estado=EstadoItem.DESCONOCIDO))

            if remoto == canonico:
                if al is not None:
                    db.delete(al)       # el canonico ya alcanza
                continue

            if al is None:
                db.add(AliasPlataforma(producto_id=p.id, plataforma=plataforma,
                                       nombre_remoto=remoto))
                log.info("alias nuevo %s/%s: '%s'", canonico, plataforma, remoto)
            elif al.nombre_remoto != remoto:
                log.info("alias %s/%s: '%s' -> '%s'",
                         canonico, plataforma, al.nombre_remoto, remoto)
                al.nombre_remoto = remoto


def _crear_todo(db):
    for i, (canonico, categoria, n_py, n_rappi) in enumerate(PRODUCTOS):
        _crear_producto(db, canonico, categoria, n_py, n_rappi, orden=i)


def _crear_producto(db, canonico, categoria, n_py, n_rappi, orden):
    p = Producto(nombre=canonico, categoria=categoria, orden=orden)
    db.add(p)
    db.flush()

    for plat, nombre in (("pedidosya", n_py), ("rappi", n_rappi)):
        # Sin nombre, el producto no existe en esa plataforma: ni alias ni
        # estado. La UI lo muestra con el chip gris "—".
        if nombre is None:
            continue
        if nombre != canonico:
            db.add(AliasPlataforma(producto_id=p.id, plataforma=plat,
                                   nombre_remoto=nombre))
        db.add(EstadoItem(producto_id=p.id, plataforma=plat,
                          estado=EstadoItem.DESCONOCIDO))
    return p
