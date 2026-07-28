"""Vincular y separar productos entre plataformas.

El modelo ya sabia decir esto sin tablas nuevas:

    un Producto con alias en las dos plataformas  = es el mismo plato,
                                                    un solo boton lo apaga
    un Producto con alias en una sola             = existe solo ahi

Lo que faltaba era poder cambiar de uno a otro desde la app, en vez de
editarlo a mano en seed.py. Es lo que pidio el usuario (2026-07-27):

    "si la app lee las cartas de cada pagina, deberia mostrar ambas si la
     opcion no es claramente la misma. Y de ultima dejarme linkear
     opciones al mismo boton de apagado"

Asi que las dudosas quedan separadas (dos filas, dos botones) y vincular
es una decision explicita que queda guardada.

OJO: cualquier decision tomada aca marca el catalogo como manual, y desde
ese momento seed.py deja de pisar los alias en cada arranque. Sin eso, un
reinicio deshacia lo que el usuario habia vinculado.
"""

import json
import logging

from .carta import parecido
from .models import Producto, AliasPlataforma, EstadoItem, Preferencia

log = logging.getLogger("catalogo")

PLATAFORMAS = ("pedidosya", "rappi")

# Para avisar "esto aparecio en el otro portal" el parecido tiene que ser
# casi identico, no solo alto. Con 0.82 (el umbral del emparejador) el
# "Tarta de verdura chica" de PedidosYa da 0.91 contra el "Tarta de verdura con
# ensalada" de Rappi, y son platos distintos: justamente lo que el usuario
# nos corrigio. Un aviso que sugiere vincular lo que no va es peor que no
# avisar, asi que aca solo entran los que son el mismo nombre salvo tildes
# o mayusculas. Lo dudoso se decide en la pantalla Carta, con todo a la vista.
UMBRAL_NOVEDAD = 0.95


def marcar_manual(db):
    """De aca en mas manda la base, no seed.py."""
    marca = db.query(Preferencia).get(Preferencia.CATALOGO_MANUAL)
    if marca is None:
        marca = Preferencia(clave=Preferencia.CATALOGO_MANUAL)
        db.add(marca)
    if marca.valor != "1":
        log.info("El catalogo pasa a mandarlo la base: seed.py deja de "
                 "sincronizar alias en cada arranque")
    marca.valor = "1"


def es_manual(db) -> bool:
    marca = db.query(Preferencia).get(Preferencia.CATALOGO_MANUAL)
    return bool(marca and marca.valor == "1")


# ---------- Busqueda ----------

def nombre_remoto(producto: Producto, plataforma: str) -> str | None:
    """Como se llama este producto en esa plataforma. None si no esta ahi."""
    if not any(e.plataforma == plataforma for e in producto.estados):
        return None
    for a in producto.alias:
        if a.plataforma == plataforma:
            return a.nombre_remoto
    return producto.nombre


def buscar_por_remoto(db, plataforma: str, remoto: str) -> Producto | None:
    """El producto que en `plataforma` se llama `remoto`, si esta cargado."""
    alias = (db.query(AliasPlataforma)
             .filter_by(plataforma=plataforma, nombre_remoto=remoto)
             .first())
    if alias is not None:
        return db.query(Producto).get(alias.producto_id)

    # Sin alias, el canonico es el nombre remoto. Igual tiene que existir en
    # esa plataforma: si no, es otro producto que se llama parecido.
    producto = db.query(Producto).filter_by(nombre=remoto).first()
    if producto is not None and nombre_remoto(producto, plataforma) == remoto:
        return producto
    return None


def _nombre_libre(db, base: str, excluir_id: int = None) -> str:
    """Producto.nombre es unico: le agregamos un sufijo si hace falta."""
    candidato = base
    intento = 2
    while True:
        choque = db.query(Producto).filter_by(nombre=candidato).first()
        if choque is None or choque.id == excluir_id:
            return candidato
        candidato = f"{base} ({intento})"
        intento += 1


# ---------- Operaciones ----------

def _poner_alias(db, producto: Producto, plataforma: str, remoto: str):
    """Deja el producto llamandose `remoto` en esa plataforma."""
    alias = (db.query(AliasPlataforma)
             .filter_by(producto_id=producto.id, plataforma=plataforma).first())

    if remoto == producto.nombre:
        # El canonico ya alcanza; un alias igual solo agrega ruido.
        if alias is not None:
            db.delete(alias)
        return

    if alias is None:
        db.add(AliasPlataforma(producto_id=producto.id, plataforma=plataforma,
                               nombre_remoto=remoto))
    else:
        alias.nombre_remoto = remoto


def _poner_estado(db, producto: Producto, plataforma: str) -> EstadoItem:
    """El EstadoItem es lo que dice 'este producto existe en esta plataforma'."""
    est = (db.query(EstadoItem)
           .filter_by(producto_id=producto.id, plataforma=plataforma).first())
    if est is None:
        est = EstadoItem(producto_id=producto.id, plataforma=plataforma,
                         estado=EstadoItem.DESCONOCIDO)
        db.add(est)
    return est


def agregar(db, plataforma: str, remoto: str, categoria: str = "",
            nombre: str = None) -> Producto:
    """Carga un producto que existe en UNA sola plataforma."""
    if plataforma not in PLATAFORMAS:
        raise ValueError(f"plataforma desconocida: {plataforma}")

    ya = buscar_por_remoto(db, plataforma, remoto)
    if ya is not None:
        return ya

    producto = Producto(nombre=_nombre_libre(db, nombre or remoto),
                        categoria=categoria, orden=500)
    db.add(producto)
    db.flush()

    _poner_alias(db, producto, plataforma, remoto)
    _poner_estado(db, producto, plataforma)
    marcar_manual(db)
    log.info("Agregado '%s' (solo %s)", producto.nombre, plataforma)
    return producto


def vincular(db, remoto_py: str, remoto_rappi: str,
             nombre: str = None, categoria: str = "") -> Producto:
    """Deja los dos nombres apuntando al MISMO producto: un solo boton.

    Sirve para los tres casos que aparecen en la carta: los dos ya estaban
    cargados por separado (se fusionan), uno solo estaba cargado (se le
    agrega la otra plataforma), o ninguno (se crea).
    """
    a = buscar_por_remoto(db, "pedidosya", remoto_py)
    b = buscar_por_remoto(db, "rappi", remoto_rappi)

    if a is not None and b is not None and a.id == b.id:
        return a                                     # ya estaban vinculados

    if a is None and b is None:
        producto = Producto(nombre=_nombre_libre(db, nombre or remoto_py),
                            categoria=categoria, orden=500)
        db.add(producto)
        db.flush()
    elif a is not None and b is None:
        producto = a
    elif a is None and b is not None:
        producto = b
    else:
        # Los dos existian por separado: se queda el de PedidosYa, que es el
        # que tiene el nombre canonico, y el de Rappi se absorbe.
        producto = a
        _absorber(db, destino=a, origen=b)

    if nombre:
        producto.nombre = _nombre_libre(db, nombre, excluir_id=producto.id)

    _poner_alias(db, producto, "pedidosya", remoto_py)
    _poner_alias(db, producto, "rappi", remoto_rappi)
    _poner_estado(db, producto, "pedidosya")
    _poner_estado(db, producto, "rappi")

    marcar_manual(db)
    log.info("Vinculados '%s' (PedidosYa) y '%s' (Rappi) como '%s'",
             remoto_py, remoto_rappi, producto.nombre)
    return producto


def _absorber(db, destino: Producto, origen: Producto):
    """Pasa lo de `origen` a `destino` y borra `origen`.

    Las operaciones en cola del producto que desaparece se remapean: si no,
    quedan apuntando a una fila borrada y el worker revienta al tomarlas.
    """
    from .models import Operacion

    (db.query(Operacion)
       .filter(Operacion.producto_id == origen.id)
       .update({"producto_id": destino.id}, synchronize_session=False))

    db.delete(origen)
    db.flush()


# ---------- Novedades: algo que aparecio en un portal donde no estaba ----------

def _ignoradas(db) -> set:
    marca = db.query(Preferencia).get(Preferencia.NOVEDADES_IGNORADAS)
    if marca is None or not marca.valor:
        return set()
    try:
        return set(json.loads(marca.valor))
    except ValueError:
        return set()


def ignorar_novedad(db, plataforma: str, remoto: str):
    """No avisar mas de este. El usuario ya lo vio y no lo quiere vincular."""
    marca = db.query(Preferencia).get(Preferencia.NOVEDADES_IGNORADAS)
    if marca is None:
        marca = Preferencia(clave=Preferencia.NOVEDADES_IGNORADAS)
        db.add(marca)
    actuales = _ignoradas(db)
    actuales.add(f"{plataforma}|{remoto}")
    marca.valor = json.dumps(sorted(actuales))


def detectar_novedades(db, plataforma: str, leidos) -> list:
    """Productos del catalogo que APARECIERON en un portal donde no estaban.

    El caso que lo motivo: la Locro figuraba como exclusiva de Rappi
    (confirmado en su momento), el usuario la agrego a la carta de PedidosYa,
    y la app la seguia mostrando en gris con el chip "no existe ahi". Sin
    este aviso, la unica forma de enterarse era acordarse de abrir la carta.

    Solo mira productos QUE YA ESTAN en el catalogo y a los que les falta
    una plataforma. Los nombres del portal que no corresponden a nada
    cargado no entran: son los ~18 de Rappi que el usuario decidio no
    cargar, y avisar de ellos en cada arranque seria puro ruido.
    """
    ignoradas = _ignoradas(db)

    # Los nombres del portal que ya tienen dueño no son novedad.
    tomados = set()
    productos = db.query(Producto).filter(Producto.activo == True).all()  # noqa: E712
    for p in productos:
        remoto = nombre_remoto(p, plataforma)
        if remoto is not None:
            tomados.add(remoto)

    sueltos = [n for n in leidos
               if n not in tomados and f"{plataforma}|{n}" not in ignoradas]
    if not sueltos:
        return []

    novedades = []
    for p in productos:
        if nombre_remoto(p, plataforma) is not None:
            continue        # ya esta en esa plataforma

        # Contra que comparamos: el canonico y como se llama en la otra.
        conocidos = [p.nombre] + [a.nombre_remoto for a in p.alias]

        mejor, punto = None, 0.0
        for suelto in sueltos:
            for conocido in conocidos:
                valor = parecido(conocido, suelto)
                if valor > punto:
                    mejor, punto = suelto, valor

        if mejor is None or punto < UMBRAL_NOVEDAD:
            continue

        otra = next((o for o in PLATAFORMAS
                     if o != plataforma and nombre_remoto(p, o) is not None), None)
        novedades.append({
            "producto_id": p.id,
            "producto": p.nombre,
            "plataforma": plataforma,
            "nombre_en_el_portal": mejor,
            "confianza": round(punto, 3),
            # Lo que hay que mandarle a /api/vincular para engancharlo.
            "pedidosya": mejor if plataforma == "pedidosya" else nombre_remoto(p, "pedidosya"),
            "rappi": mejor if plataforma == "rappi" else nombre_remoto(p, "rappi"),
            "otra_plataforma": otra,
        })

    if novedades:
        log.info("%s: aparecieron en el portal %s productos que el catalogo "
                 "tenia como inexistentes ahi: %s", plataforma, len(novedades),
                 ", ".join(n["nombre_en_el_portal"] for n in novedades))
    return novedades


def separar(db, producto_id: int, plataforma: str) -> Producto:
    """Saca una plataforma del producto y la deja como producto aparte.

    Es lo contrario de vincular: para cuando la app dio por iguales dos
    platos que no lo son. El caso que lo motivo: "Tarta de verdura chica"
    de PedidosYa NO es "Tarta de verdura individual" de Rappi (confirmado por
    el usuario, 2026-07-27).
    """
    if plataforma not in PLATAFORMAS:
        raise ValueError(f"plataforma desconocida: {plataforma}")

    producto = db.query(Producto).get(producto_id)
    if producto is None:
        raise ValueError("producto no encontrado")

    remoto = nombre_remoto(producto, plataforma)
    if remoto is None:
        raise ValueError(f"'{producto.nombre}' no esta en {plataforma}")

    otras = [p for p in PLATAFORMAS
             if p != plataforma and nombre_remoto(producto, p) is not None]
    if not otras:
        raise ValueError(f"'{producto.nombre}' solo esta en {plataforma}: "
                         "no hay nada que separar")

    nuevo = Producto(nombre=_nombre_libre(db, remoto),
                     categoria=producto.categoria, orden=producto.orden)
    db.add(nuevo)
    db.flush()

    # El estado real de la plataforma que se va viaja con ella.
    viejo_estado = (db.query(EstadoItem)
                    .filter_by(producto_id=producto.id, plataforma=plataforma)
                    .first())
    estado_nuevo = _poner_estado(db, nuevo, plataforma)
    if viejo_estado is not None:
        estado_nuevo.estado = viejo_estado.estado
        estado_nuevo.detalle = viejo_estado.detalle
        estado_nuevo.verificado_en = viejo_estado.verificado_en
        db.delete(viejo_estado)

    alias_viejo = (db.query(AliasPlataforma)
                   .filter_by(producto_id=producto.id, plataforma=plataforma)
                   .first())
    if alias_viejo is not None:
        db.delete(alias_viejo)
    _poner_alias(db, nuevo, plataforma, remoto)

    marcar_manual(db)
    log.info("Separado: '%s' en %s pasa a ser el producto '%s'",
             producto.nombre, plataforma, nuevo.nombre)
    return nuevo
