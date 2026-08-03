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
from .models import (Producto, AliasPlataforma, EstadoItem, Preferencia,
                     HistorialCatalogo)

log = logging.getLogger("catalogo")

# "rappi_comun" es una tienda de Rappi independiente de "rappi" (Turbo):
# mismo portal, mismo login, pero apagar en una no apaga en la otra. Es
# opcional (ver app/config.py, rappi_comun_store_id); si no esta configurada
# el worker ni le abre pestaña, y no aparece en ningun catalogo real.
PLATAFORMAS = ("pedidosya", "rappi", "rappi_comun")

# Para avisar "esto aparecio en el otro portal" el parecido tiene que ser
# casi identico, no solo alto. Con 0.82 (el umbral del emparejador) una
# "Tarta de verdura chica" da 0.83 contra una "Tarta de verdura porción",
# y son platos distintos. Un aviso que sugiere vincular lo que no va es
# peor que no avisar, asi que aca solo entran los que son el mismo nombre
# salvo tildes o mayusculas. Lo dudoso se decide en la pantalla Carta,
# con todo a la vista.
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


# ---------- Deshacer ----------

def _foto(db) -> str:
    """Serializa el catalogo entero. Es chico: 30 productos."""
    productos = []
    for p in db.query(Producto).all():
        productos.append({
            "id": p.id, "nombre": p.nombre, "categoria": p.categoria,
            "orden": p.orden, "activo": bool(p.activo),
            "pausado": bool(p.pausado),
            "alias": [{"plataforma": a.plataforma, "remoto": a.nombre_remoto}
                      for a in p.alias],
            "estados": [{"plataforma": e.plataforma, "estado": e.estado,
                         "detalle": e.detalle} for e in p.estados],
        })
    return json.dumps(productos, ensure_ascii=False)


def guardar_paso(db, descripcion: str):
    """Saca la foto ANTES de tocar nada. La llaman vincular/separar/agregar."""
    db.add(HistorialCatalogo(descripcion=descripcion, datos=_foto(db)))
    db.flush()

    viejos = (db.query(HistorialCatalogo)
              .order_by(HistorialCatalogo.id.desc())
              .offset(HistorialCatalogo.MAXIMO).all())
    for v in viejos:
        db.delete(v)


def hay_para_deshacer(db) -> str | None:
    """Que cambio deshace el proximo 'Deshacer'."""
    paso = (db.query(HistorialCatalogo)
            .order_by(HistorialCatalogo.id.desc()).first())
    return paso.descripcion if paso else None


def deshacer(db) -> str | None:
    """Vuelve el catalogo a como estaba antes del ultimo cambio.

    Reconstruye productos, alias y estados con los MISMOS ids, para no
    dejar colgadas las operaciones del historial que los referencian.
    """
    paso = (db.query(HistorialCatalogo)
            .order_by(HistorialCatalogo.id.desc()).first())
    if paso is None:
        return None

    productos = json.loads(paso.datos)
    descripcion = paso.descripcion
    paso_id = paso.id

    db.query(AliasPlataforma).delete(synchronize_session=False)
    db.query(EstadoItem).delete(synchronize_session=False)
    db.query(Producto).delete(synchronize_session=False)
    db.flush()

    # El borrado masivo no pasa por el identity map: la sesion sigue con los
    # objetos viejos en memoria y, al reinsertar un producto con el mismo id,
    # arrastra por cascada los alias que ya no existen (UNIQUE violado).
    # Vaciar la sesion la obliga a leer de nuevo de la base.
    db.expunge_all()

    for p in productos:
        db.add(Producto(
            id=p["id"], nombre=p["nombre"], categoria=p["categoria"],
            orden=p["orden"], activo=p["activo"], pausado=p["pausado"],
        ))
    db.flush()

    for p in productos:
        for a in p["alias"]:
            db.add(AliasPlataforma(producto_id=p["id"],
                                   plataforma=a["plataforma"],
                                   nombre_remoto=a["remoto"]))
        for e in p["estados"]:
            db.add(EstadoItem(producto_id=p["id"], plataforma=e["plataforma"],
                              estado=e["estado"], detalle=e["detalle"]))

    db.query(HistorialCatalogo).filter_by(id=paso_id).delete(
        synchronize_session=False)
    log.info("Deshecho: %s", descripcion)
    return descripcion


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


NOMBRE_PLATAFORMA = {"pedidosya": "PedidosYa", "rappi": "Rappi",
                     "rappi_comun": "Rappi Común"}


def _nombre_libre(db, base: str, excluir_id: int = None,
                  plataforma: str = None) -> str:
    """Producto.nombre es unico: le agregamos algo si hace falta.

    Primero se prueba el nombre de la plataforma y recien despues un
    numero. Al separar dos que se llamaban igual quedaba "Tarta (2)", que
    no le dice nada a nadie; "Tarta (PedidosYa)" se entiende.
    """
    def libre(nombre):
        choque = db.query(Producto).filter_by(nombre=nombre).first()
        return choque is None or choque.id == excluir_id

    if libre(base):
        return base

    if plataforma:
        con_plataforma = f"{base} ({NOMBRE_PLATAFORMA.get(plataforma, plataforma)})"
        if libre(con_plataforma):
            return con_plataforma

    intento = 2
    while True:
        candidato = f"{base} ({intento})"
        if libre(candidato):
            return candidato
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

    guardar_paso(db, f"agregar '{remoto}' "
                     f"({NOMBRE_PLATAFORMA.get(plataforma, plataforma)})")

    producto = Producto(nombre=_nombre_libre(db, nombre or remoto,
                                             plataforma=plataforma),
                        categoria=categoria, orden=500)
    db.add(producto)
    db.flush()

    _poner_alias(db, producto, plataforma, remoto)
    _poner_estado(db, producto, plataforma)
    marcar_manual(db)
    log.info("Agregado '%s' (solo %s)", producto.nombre, plataforma)
    return producto


def enlazar(db, producto_id: int, plataforma: str, remoto: str) -> Producto:
    """Suma una plataforma a un producto que YA EXISTE, sin crear uno nuevo.

    `vincular()` fusiona/crea a partir de PedidosYa + Rappi, que es el par
    principal. Esto es para el caso de agregarle una plataforma MAS a un
    producto que ya esta cargado (hoy, Rappi Común: un plato que ya se
    apaga en PedidosYa y en Rappi Turbo y ahora tambien hay que apagarlo
    ahi). Se usa desde el aviso de "novedad" cuando la plataforma no es
    ninguna de las dos principales.
    """
    if plataforma not in PLATAFORMAS:
        raise ValueError(f"plataforma desconocida: {plataforma}")

    producto = db.query(Producto).get(producto_id)
    if producto is None:
        raise ValueError("producto no encontrado")

    ya = buscar_por_remoto(db, plataforma, remoto)
    if ya is not None and ya.id != producto.id:
        raise ValueError(f"'{remoto}' ya está cargado como '{ya.nombre}'")

    guardar_paso(db, f"agregar {NOMBRE_PLATAFORMA.get(plataforma, plataforma)} "
                     f"a '{producto.nombre}'")

    _poner_alias(db, producto, plataforma, remoto)
    _poner_estado(db, producto, plataforma)
    marcar_manual(db)
    log.info("'%s' ahora también existe en %s como '%s'",
             producto.nombre, plataforma, remoto)
    return producto


def vincular(db, remoto_py: str, remoto_rappi: str,
             nombre: str = None, categoria: str = "") -> Producto:
    """Deja los dos nombres apuntando al MISMO producto: un solo boton.

    Es el par principal (PedidosYa + Rappi Turbo). Para vincular tres de una
    —hoy sumando Rappi Común— esta `vincular_varios()`, que es lo mismo con
    un diccionario.
    """
    return vincular_varios(db, {"pedidosya": remoto_py, "rappi": remoto_rappi},
                           nombre=nombre, categoria=categoria)


def vincular_varios(db, nombres: dict, nombre: str = None,
                    categoria: str = "") -> Producto:
    """Deja todos esos nombres apuntando al MISMO producto: un solo boton.

    `nombres` es {plataforma: nombre_en_ese_portal}, con las plataformas que
    quieras: dos (el par de siempre) o tres (sumando la tienda Rappi Común).
    Una plataforma que no este en el diccionario NO se toca — es la unica
    forma de vincular PedidosYa con Turbo sin decir nada de Común, que es
    justo lo que hace falta cuando la tercera todavia esta en duda.

    Sirve para los mismos casos de siempre: ya estaban cargados por separado
    (se fusionan), alguno estaba cargado (se le agregan las demas), o ninguno
    (se crea).
    """
    nombres = {plat: remoto for plat, remoto in nombres.items() if remoto}
    desconocidas = [p for p in nombres if p not in PLATAFORMAS]
    if desconocidas:
        raise ValueError(f"plataforma desconocida: {desconocidas[0]}")
    if len(nombres) < 2:
        raise ValueError("hay que vincular al menos dos plataformas")

    # En el orden de PLATAFORMAS: el nombre canonico sale del primero que
    # haya (PedidosYa si esta), como venia siendo.
    orden = [p for p in PLATAFORMAS if p in nombres]

    existentes = {plat: buscar_por_remoto(db, plat, nombres[plat])
                  for plat in orden}
    encontrados = [p for p in existentes.values() if p is not None]

    if encontrados and all(p.id == encontrados[0].id for p in encontrados) \
            and len(encontrados) == len(orden):
        return encontrados[0]                        # ya estaban vinculados

    guardar_paso(db, "vincular " + " con ".join(
        f"'{nombres[p]}' ({NOMBRE_PLATAFORMA.get(p, p)})" for p in orden))

    # Antes de juntar, hay que soltar lo que estos ya tenian tomado en las
    # plataformas que se estan reasignando, o se perderia sin aviso. Pasa al
    # vincular a mano dos que ya estaban emparejados con otra cosa: si "Tarta
    # de verdura chica" (PY) se vincula con "Tarta de verdura" (Rappi), y ese
    # ya estaba con la "Tarta de verdura" (PY), ese ultimo se quedaba sin
    # plataforma y desaparecia del catalogo. Ahora sobrevive como producto
    # propio.
    for producto in encontrados:
        for plat in orden:
            actual = nombre_remoto(producto, plat)
            if actual is not None and actual != nombres[plat]:
                log.info("'%s' se suelta de '%s' (%s) para vincularse con '%s'",
                         producto.nombre, actual,
                         NOMBRE_PLATAFORMA.get(plat, plat), nombres[plat])
                separar(db, producto.id, plat, registrar=False)

    # separar() borra alias y estados, pero la sesion es autoflush=False y
    # las colecciones en memoria siguen mostrando lo que ya no esta. Sin
    # esto, el absorber de abajo se llevaba a `destino` un alias que acababa
    # de mudarse a otro producto, y el mismo nombre de portal quedaba en dos.
    db.flush()
    db.expire_all()
    existentes = {plat: buscar_por_remoto(db, plat, nombres[plat])
                  for plat in orden}
    encontrados = [p for p in existentes.values() if p is not None]

    if not encontrados:
        producto = Producto(nombre=_nombre_libre(db, nombre or nombres[orden[0]]),
                            categoria=categoria, orden=500)
        db.add(producto)
        db.flush()
    else:
        # Se queda el del portal que va primero (PedidosYa si esta, que es el
        # que tiene el nombre canonico) y los demas se absorben.
        producto = next(existentes[p] for p in orden if existentes[p] is not None)
        for otro in encontrados:
            if otro.id != producto.id:
                _absorber(db, destino=producto, origen=otro)

    if nombre:
        producto.nombre = _nombre_libre(db, nombre, excluir_id=producto.id)

    for plat in orden:
        _poner_alias(db, producto, plat, nombres[plat])
        _poner_estado(db, producto, plat)

    marcar_manual(db)
    log.info("Vinculados %s como '%s'",
             ", ".join(f"'{nombres[p]}' ({NOMBRE_PLATAFORMA.get(p, p)})"
                       for p in orden), producto.nombre)
    return producto


def _absorber(db, destino: Producto, origen: Producto):
    """Pasa lo de `origen` a `destino` y borra `origen`.

    Las operaciones en cola del producto que desaparece se remapean: si no,
    quedan apuntando a una fila borrada y el worker revienta al tomarlas.

    Las plataformas que `origen` tenia y `destino` no, se mudan con todo y
    estado. Con dos plataformas esto no podia pasar (las dos se reescribian
    despues igual), pero con tres si: absorber un producto que ya estaba
    vinculado a la tienda Común mientras vinculas PedidosYa con Turbo le
    borraba esa tercera sin decir nada. Si `destino` YA tiene esa
    plataforma, la de `origen` no se puede mudar: se separa antes, y
    sobrevive como producto suelto en vez de desaparecer.
    """
    from .models import Operacion

    for plat in list(PLATAFORMAS):
        suyo = nombre_remoto(origen, plat)
        if suyo is None:
            continue
        if nombre_remoto(destino, plat) is not None:
            # Los dos lo tienen y no son el mismo nombre: el de origen no
            # cabe. Se va como producto propio antes de que lo borremos.
            if len([p for p in PLATAFORMAS
                    if nombre_remoto(origen, p) is not None]) > 1:
                log.info("'%s' (%s) no cabe en '%s': queda como producto suelto",
                         suyo, NOMBRE_PLATAFORMA.get(plat, plat), destino.nombre)
                separar(db, origen.id, plat, registrar=False)
            continue

        estado_viejo = next((e for e in origen.estados
                             if e.plataforma == plat), None)
        _poner_alias(db, destino, plat, suyo)
        est = _poner_estado(db, destino, plat)
        if estado_viejo is not None:
            est.estado = estado_viejo.estado
            est.detalle = estado_viejo.detalle
            est.verificado_en = estado_viejo.verificado_en
        log.info("'%s' se lleva %s ('%s') de '%s'", destino.nombre,
                 NOMBRE_PLATAFORMA.get(plat, plat), suyo, origen.nombre)

    db.flush()

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

    El caso que lo motivo: un plato figuraba como exclusivo de Rappi
    (confirmado en su momento), el usuario lo agrego a la carta de PedidosYa,
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


# ---------- Dos tiendas del mismo portal que quedaron distintas ----------

def desparejos(db, activas, desde=None) -> list:
    """Lo que quedo APAGADO en una tienda y PRENDIDO en la tienda hermana.

    Rappi Turbo y Rappi Común son dos tiendas del mismo local con dos
    toggles independientes. Un producto vinculado en las dos que quedo
    apagado en una sola se sigue vendiendo en la otra, y en la pantalla eso
    no se ve: son dos chips distintos, uno rojo y otro verde, en una fila
    que a simple vista parece atendida.

    Lo que NO entra aca, a proposito: el producto que directamente no esta
    vinculado en la otra tienda. Puede que ahi no se venda, y no hay forma
    de distinguirlo desde la base — eso se resuelve una vez en la pantalla
    de asociacion (y el aviso de novedad ya lo empuja). Un cartel fijo
    diciendo "esto podria estar en la otra tienda" para media carta se
    vuelve ruido, y el ruido termina en que no se lee ninguno.

    `desde` es la frontera de lo que se puede afirmar: si alguno de los dos
    estados no se verifico despues de ese momento, la familia se saltea.
    Sin `desde` no se filtra nada (comportamiento viejo).

    POR QUE (log del 2026-08-03): al arrancar, la app termino de leer Rappi
    Comun dos minutos antes que Rappi. En esa ventana esta funcion cruzo lo
    recien leido contra el estado del dia anterior y la pantalla afirmo que
    11 productos se seguian vendiendo en la tienda hermana. Cuando Rappi
    termino de leerse quedo 1: los otros 10 eran datos viejos. Comparar dos
    estados es afirmar sobre los dos, y de uno no estabamos viendo nada
    (regla 8). Lo viejo ya tiene su propio aviso, `sin_confirmar`, que dice
    lo que corresponde ahi: hay que releer.
    """
    from .carta import TIENDAS_DEL_MISMO_PORTAL

    familias = [sorted(f & set(activas)) for f in TIENDAS_DEL_MISMO_PORTAL]
    familias = [f for f in familias if len(f) > 1]
    if not familias:
        return []

    salida = []
    productos = (db.query(Producto)
                 .filter(Producto.activo == True)  # noqa: E712
                 .order_by(Producto.orden).all())

    for p in productos:
        if p.pausado:
            continue                 # el usuario ya dijo que no le importa
        for familia in familias:
            estados = {e.plataforma: e for e in p.estados
                       if e.plataforma in familia}
            # Con una operacion en vuelo lo que diga el estado es
            # transitorio: avisar ahi seria avisar de algo que se esta
            # arreglando solo en este momento.
            if any(e.estado in EstadoItem.EN_CURSO for e in estados.values()):
                continue

            # Un estado sin confirmar hace rato no sirve para comparar: no
            # se puede decir "en la otra se sigue vendiendo" mirando lo que
            # el portal decia ayer.
            if desde is not None and any(
                    e.verificado_en is None or e.verificado_en < desde
                    for e in estados.values()):
                continue

            apagadas = [plat for plat, e in estados.items()
                        if e.estado in EstadoItem.APAGADOS_PROPIOS
                        or e.estado == EstadoItem.APAGADO_AJENO]
            prendidas = [plat for plat, e in estados.items()
                         if e.estado == EstadoItem.PRENDIDO]
            if not apagadas or not prendidas:
                continue

            salida.append({
                "producto_id": p.id,
                "producto": p.nombre,
                "apagada_en": apagadas[0],
                "prendida_en": prendidas[0],
                "nombre_remoto": nombre_remoto(p, prendidas[0]),
                "estado": estados[apagadas[0]].estado,
            })

    _loguear_desparejos(salida)
    return salida


# Lo ultimo que se logueo, para no repetirlo. Es memoria de proceso y no de
# base a proposito: si se reinicia la app, que lo diga una vez mas no
# molesta, y asi no hay una tabla que mantener para un mensaje de log.
_ultimos_desparejos: set = set()


def _loguear_desparejos(salida: list) -> None:
    """El aviso al log, pero solo cuando CAMBIA.

    desparejos() es calculo puro y la pantalla la llama por /api/alertas
    cada 3 segundos: con el log adentro, la misma linea salia 20 veces por
    minuto y tapaba todo lo demas (log del 2026-08-03). Lo que importa es
    la transicion, no el estado.
    """
    global _ultimos_desparejos

    ahora = {s["producto_id"] for s in salida}
    if ahora == _ultimos_desparejos:
        return
    _ultimos_desparejos = ahora

    if salida:
        log.info("%s producto(s) apagados en una tienda y prendidos en la "
                 "hermana: %s", len(salida),
                 ", ".join(s["producto"] for s in salida))
    else:
        # Esto antes no se veia nunca (el log estaba adentro de un `if
        # salida`), asi que el aviso quedaba abierto en el log para siempre.
        log.info("Ya no queda nada apagado en una tienda y prendido en la "
                 "hermana")


def separar(db, producto_id: int, plataforma: str,
            registrar: bool = True) -> Producto:
    """Saca una plataforma del producto y la deja como producto aparte.

    Es lo contrario de vincular: para cuando la app dio por iguales dos
    platos que no lo son. El caso que lo motivo: una "Tarta de verdura
    chica" de PedidosYa NO era la "Tarta de verdura porción" de Rappi (dicho por
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

    if registrar:
        guardar_paso(db, f"separar '{producto.nombre}' de "
                         f"{NOMBRE_PLATAFORMA.get(plataforma, plataforma)}")

    # La pausa viaja con el producto: si el plato estaba en pausa, sus dos
    # mitades siguen estandolo. Si no, separar lo devolvia solo a la lista.
    nuevo = Producto(nombre=_nombre_libre(db, remoto, plataforma=plataforma),
                     categoria=producto.categoria, orden=producto.orden,
                     pausado=producto.pausado)
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
