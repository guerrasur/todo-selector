"""Carga inicial del catalogo. Viene VACIA a proposito.

Una instalacion nueva no tiene por que arrancar con la carta de otro local.
Antes este archivo traia los 31 productos del local para el que se escribio
la app, con sus nombres en cada portal: quien clonara el repo se encontraba
con una carta ajena y tenia que borrarla a mano.

Ahora el primer arranque no carga nada y la pantalla ofrece **leer tu
carta**: la app entra a los dos portales, lee lo que hay y arma el catalogo
sola (ver app/carta.py y app/catalogo.py). Es el mismo camino que ya se usa
para agregar un producto nuevo, asi que no hay codigo que mantener aparte.

Esto NO le borra el catalogo a nadie: `sembrar()` solo crea productos si la
base esta vacia, y ademas en cuanto el usuario vincula o separa algo desde
la app la base pasa a mandar (`es_manual`). Una instalacion que ya venia
funcionando sigue con su catalogo intacto.

La maquinaria de abajo se deja porque sigue sirviendo: si alguien quiere
arrancar con una lista escrita a mano, llena PRODUCTOS y listo. Formato:

    (nombre_canonico, categoria, nombre_en_pedidosya, nombre_en_rappi)

Un nombre en None quiere decir que el producto NO existe en esa plataforma.
Ojo con las tildes: los nombres se buscan en el portal con exact=True.
"""

import logging

from .catalogo import es_manual
from .database import SessionLocal
from .models import Producto, AliasPlataforma, EstadoItem

log = logging.getLogger("seed")

# (canonico, categoria, pedidosya, rappi). Vacia: ver el docstring.
PRODUCTOS = []

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

    Lo segundo hace falta para poder desvincular: al marcar un producto como
    exclusivo de PedidosYa, sin esto la base se quedaba con el alias de
    Rappi y lo seguia apagando alla.
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
