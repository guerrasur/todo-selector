"""Carga inicial de productos con sus nombres en cada plataforma.

IMPORTANTE: los nombres difieren mucho entre PedidosYa y Rappi.
Formato: (nombre_canonico, categoria, nombre_en_pedidosya, nombre_en_rappi)
Si un nombre es None, ese producto NO existe en esa plataforma.

REVISAR LAS MARCAS "DUDA" ANTES DE USAR EN PRODUCCION.

Las tildes de los nombres de Rappi salen del portal mismo, via /api/nombres
(2026-07-27). Sin tilde no se encuentran: se buscan con exact=True.

OJO: esta lista esta INCOMPLETA. El portal de Rappi muestra 45 productos y
aca hay 30. Ver la lista de faltantes en el README.
"""

import logging

from .database import SessionLocal
from .models import Producto, AliasPlataforma, EstadoItem

log = logging.getLogger("seed")

# (canonico, categoria, pedidosya, rappi)
PRODUCTOS = [
    # ---------------- Ensaladas ----------------
    ("Caesar", "Ensaladas", "Caesar", "Ensalada caesar"),
    ("Cobb", "Ensaladas", "Cobb", "Cobb"),
    ("Clasica", "Ensaladas", "Clasica", "Ensalada clásica"),
    ("Brie", "Ensaladas", "Brie", "Ensalada Brie"),
    ("Atun", "Ensaladas", "Atun", "Ensalada con atún"),
    ("Falafel", "Ensaladas", "Falafel", "Ensalada de falafel"),
    ("Cala", "Ensaladas", "Cala", "Ensalada cala"),
    ("Porto", "Ensaladas", "Porto", "Ensalada porto"),

    # Mexicana: descontinuada, no se usa mas. Se deja comentada por si vuelve.
    # ("Mexicana", "Ensaladas", "Mexicana", None),

    # CONFIRMADO: "Ensalada con Peras" no existe en PedidosYa.
    ("Ensalada con Peras", "Ensaladas", None, "Ensalada con Peras"),

    # ---------------- Wraps ----------------
    ("Wrap brie", "Wraps", "Wrap brie", "Wrap Brie"),
    ("Wrap caesar", "Wraps", "Wrap caesar", "Wrap caesar"),
    ("Wrap Hummus", "Wraps", "Wrap Hummus", "Wrap Hummus"),
    ("Wrap de pollo a la Toscana", "Wraps",
     "Wrap de pollo a la Toscana", "Wrap de pollo a la toscana"),

    # DUDA IMPORTANTE: en PedidosYa dice "con batatas", en Rappi "con ensalada".
    # Asumo que son el mismo producto con distinta guarnicion en el nombre.
    # CONFIRMAR: son el mismo plato o son distintos?
    ("Wrap caesar con batatas", "Wraps",
     "Wrap caesar con batatas", "Wrap caesar con ensalada"),
    ("Wrap de Atun con batatas", "Wraps",
     "Wrap de Atun con batatas", "Wrap de atun con ensalada"),
    ("Wrap hummus con batatas", "Wraps",
     "Wrap hummus con batatas", "Wrap Hummus con ensalada"),
    ("Wrap toscano con batatas", "Wraps",
     "Wrap toscano con batatas", "Wrap Toscano con ensalada"),

    # CONFIRMADO: "Wrap de atun" (sin guarnicion) no existe en PedidosYa.
    ("Wrap de atun", "Wraps", None, "Wrap de atun"),
    # CONFIRMADO: "Wrap Brie con ensalada" no existe en PedidosYa.
    ("Wrap Brie con ensalada", "Wraps", None, "Wrap Brie con ensalada"),

    # ---------------- Platos ----------------
    # En PedidosYa estos figuran bajo "Ensaladas"; en Rappi bajo "Plato del Dia".
    # Los dejo como categoria propia para que se vean juntos en la UI.
    ("Arroz Chaufa", "Platos", "Arroz Chaufa", "Arroz Chaufa"),
    ("Risotto", "Platos", "Risotto", "Risotto de Hongos"),
    ("Pastel de papa", "Platos", "Pastel de papa", "Pastel de Papa"),
    ("Ravioles con crema de hongos", "Platos",
     "Ravioles con crema de hongos", "Ravioles con Crema de hongos"),
    ("Guiso de lentejas", "Platos", "Guiso de lentejas", "Guiso de lentejas"),
    ("Guiso de lentejas vegetariano", "Platos",
     "Guiso de lentejas vegetariano", "Guiso de lentejas vegetariano"),

    # CONFIRMADO: la Suprema no existe en PedidosYa.
    ("Suprema a la Crema de Limon con Pure", "Platos",
     None, "Suprema a la Crema de Limón con Puré"),

    # ---------------- Bebidas ----------------
    ("Agua sin gas", "Bebidas", "Agua sin gas", "Villavicencio sin gas 500 ml"),
    ("Agua con gas", "Bebidas", "Agua con gas", "Villavicencio con gas 500 ml"),
    ("Coca Cola", "Bebidas", "Coca Cola", "Coca-cola sabor original 500 ml"),

    # CONFIRMADO: en PedidosYa se cargo mal y quedo "Coca Coca Zero".
    # El nombre esta asi en el portal, no es un typo de esta lista.
    # CONFIRMADO POR /api/buscar-texto (2026-07-27): en Rappi lleva tilde,
    # "azúcar". Los nombres se buscan con exact=True, asi que sin la tilde
    # no lo encontraba.
    ("Coca Zero", "Bebidas", "Coca Coca Zero", "Coca-cola sin azúcar 500 ml"),
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
        else:
            _sincronizar_alias(db)
        db.commit()
    finally:
        db.close()


def _sincronizar_alias(db):
    """Corre en cada arranque: el catalogo manda sobre los nombres remotos.

    Este proyecto no tiene migraciones. Sin esto, corregir un nombre en
    PRODUCTOS no servia de nada en una base ya sembrada: los alias viejos
    quedaban para siempre y el producto seguia sin encontrarse en el portal.
    """
    for canonico, _categoria, n_py, n_rappi in PRODUCTOS:
        p = db.query(Producto).filter_by(nombre=canonico).first()
        if p is None:
            continue

        for plataforma, remoto in (("pedidosya", n_py), ("rappi", n_rappi)):
            if not remoto or remoto == canonico:
                continue

            al = (db.query(AliasPlataforma)
                  .filter_by(producto_id=p.id, plataforma=plataforma).first())
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
        p = Producto(nombre=canonico, categoria=categoria, orden=i)
        db.add(p)
        db.flush()

        # Alias solo si difiere del canonico
        if n_py and n_py != canonico:
            db.add(AliasPlataforma(producto_id=p.id, plataforma="pedidosya",
                                   nombre_remoto=n_py))
        if n_rappi and n_rappi != canonico:
            db.add(AliasPlataforma(producto_id=p.id, plataforma="rappi",
                                   nombre_remoto=n_rappi))

        # Solo creamos estado en las plataformas donde el producto existe
        for plat, nombre in (("pedidosya", n_py), ("rappi", n_rappi)):
            if nombre is None:
                continue
            db.add(EstadoItem(producto_id=p.id, plataforma=plat,
                              estado=EstadoItem.DESCONOCIDO))
