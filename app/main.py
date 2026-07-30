"""API + frontend de Todo-Selector."""

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import catalogo, cierre, config
from .database import init_db, get_db
from .models import Producto, AliasPlataforma, EstadoItem, Operacion, Preferencia
from .seed import sembrar
from .worker import worker

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")


# La pantalla se repinta sola cada 3 segundos y en cada vuelta pide cuatro
# endpoints. Uvicorn loguea una linea por request, asi que son ~80 lineas por
# minuto de "GET /api/productos 200 OK" que tapan lo unico que vale la pena
# mirar en esa ventana: que hizo el worker y que fallo. El usuario termino
# cerrando la app porque el log se hacia inmanejable (2026-07-28).
ENDPOINTS_DE_REFRESCO = {
    "/api/productos",
    "/api/estado-sistema",
    "/api/novedades",
    "/api/alertas",
}


class SinRuidoDeRefresco(logging.Filter):
    """Saca del log los GET del repintado que salieron bien.

    Solo esos: un POST (una accion que pediste), un 4xx o un 5xx se siguen
    viendo siempre. Si el filtro no entiende el record, deja pasar: perder
    una linea de log por las dudas es peor que loguear de mas.
    """

    def filter(self, record):
        args = getattr(record, "args", None)
        if not args or len(args) < 5:
            return True

        metodo, ruta, codigo = args[1], args[2], args[4]
        if metodo != "GET":
            return True
        try:
            if int(codigo) >= 400:
                return True
        except (TypeError, ValueError):
            return True

        return str(ruta).split("?")[0] not in ENDPOINTS_DE_REFRESCO


def silenciar_ruido_de_refresco():
    """Se llama en el startup, no al importar.

    uvicorn.run() configura el logging el solo (dictConfig) DESPUES de que
    este modulo se importa, y eso se lleva puesto cualquier filtro que le
    hubieramos puesto antes. Desde el evento de startup ya esta configurado.
    """
    log_acceso = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, SinRuidoDeRefresco) for f in log_acceso.filters):
        log_acceso.addFilter(SinRuidoDeRefresco())

app = FastAPI(title="Todo-Selector")

RAIZ = Path(__file__).resolve().parent.parent
STATIC = RAIZ / "static"

MODO_SIMULADO = os.environ.get("STOCKSWITCH_SIMULADO", "0") == "1"

# El .bat actualiza ANTES de levantar el server: si la ventana queda abierta,
# segui corriendo el codigo viejo aunque los archivos ya esten nuevos. Esto
# lo hace visible en vez de que se note como un 404 raro.
ARRANCADO_EN = datetime.now()

# Un numero que se bumpea a mano en cada cambio que vale la pena distinguir
# (ver VERSION en la raiz). No es la version de un paquete: es solo para que
# la pantalla y el log de actualizar.ps1 puedan decir "estoy en la X" y
# "pase de la X a la Y" sin que el usuario tenga que leer un commit.
def _leer_version() -> str:
    try:
        return (RAIZ / "VERSION").read_text(encoding="utf-8").strip() or "?"
    except OSError:
        return "?"


VERSION = _leer_version()


@app.on_event("startup")
async def arrancar():
    silenciar_ruido_de_refresco()
    init_db()
    sembrar()
    config.recargar()
    await worker.iniciar(modo_simulado=MODO_SIMULADO)


@app.on_event("shutdown")
async def apagar_app():
    await worker.detener()


# ---------- Schemas ----------

class AccionIn(BaseModel):
    producto_id: int
    accion: str                      # apagar_hoy | apagar_indef | prender
    plataformas: list[str] = ["pedidosya", "rappi"]


class AliasIn(BaseModel):
    producto_id: int
    plataforma: str
    nombre_remoto: str


# ---------- Endpoints ----------

@app.get("/api/productos")
def listar_productos(db: Session = Depends(get_db)):
    productos = (
        db.query(Producto)
        .filter(Producto.activo == True)  # noqa: E712
        .order_by(Producto.orden)
        .all()
    )

    salida = []
    for p in productos:
        estados = {e.plataforma: e for e in p.estados}
        alias = {a.plataforma: a.nombre_remoto for a in p.alias}

        salida.append({
            "id": p.id,
            "nombre": p.nombre,
            "categoria": p.categoria,
            "pausado": bool(p.pausado),
            "alias": alias,
            "estados": {
                plat: {
                    "estado": est.estado,
                    "detalle": est.detalle,
                    "verificado_en": est.verificado_en.isoformat()
                                     if est.verificado_en else None,
                }
                for plat, est in estados.items()
            },
        })
    return salida


@app.post("/api/accion")
def encolar_accion(data: AccionIn, db: Session = Depends(get_db)):
    producto = db.query(Producto).get(data.producto_id)
    if producto is None:
        raise HTTPException(404, "producto no encontrado")

    if data.accion not in cierre.ACCIONES:
        raise HTTPException(400, "accion invalida")

    desconocidas = [p for p in data.plataformas if p not in catalogo.PLATAFORMAS]
    if desconocidas:
        raise HTTPException(400, f"plataforma desconocida: {desconocidas[0]}")

    activas = config.plataformas_activas()

    creadas, salteadas = [], []
    for plat in data.plataformas:
        # Plataforma apagada en Ajustes (o pantalla vieja, que se repinta
        # sola pero el click puede salir con los datos de antes): no hay
        # pestaña, asi que la operacion no tendria a donde ir.
        if plat not in activas:
            salteadas.append({"plataforma": plat,
                              "motivo": "no está activa en esta instalación"})
            continue

        # El EstadoItem es lo que dice "este producto existe en esta
        # plataforma". Sin el, la operacion buscaria el nombre canonico en un
        # portal donde el producto no esta y fallaria tres veces antes de
        # decirlo. Pasa con una pantalla vieja: la lista se repinta sola,
        # pero el click puede salir con los datos de antes.
        est = (db.query(EstadoItem)
               .filter_by(producto_id=data.producto_id, plataforma=plat)
               .first())
        if est is None:
            salteadas.append({"plataforma": plat,
                              "motivo": "el producto no existe en ese portal"})
            continue

        # Sin esto, dos clicks seguidos encolan la misma operacion dos veces
        # y el segundo pasa por todo el circuito (refrescar, leer, clickear)
        # para terminar en "ya estaba apagado". Con "Apagar todo" serian 30.
        repetida = (db.query(Operacion)
                    .filter(Operacion.producto_id == data.producto_id,
                            Operacion.plataforma == plat,
                            Operacion.accion == data.accion,
                            Operacion.estado.in_([Operacion.PENDIENTE,
                                                  Operacion.EN_CURSO]))
                    .first())
        if repetida is not None:
            salteadas.append({"plataforma": plat, "motivo": "ya estaba encolada"})
            continue

        db.add(Operacion(
            producto_id=data.producto_id,
            plataforma=plat,
            accion=data.accion,
        ))

        # Marcamos estado transitorio para feedback inmediato en la UI
        est.estado = (EstadoItem.PRENDIENDO if data.accion == "prender"
                      else EstadoItem.APAGANDO)
        creadas.append(plat)

    db.commit()
    return {"encoladas": creadas, "salteadas": salteadas}


class MasivoIn(BaseModel):
    accion: str                                  # apagar_hoy|apagar_indef|prender
    plataformas: list[str] = ["pedidosya", "rappi"]
    # None = como diga Ajustes. La pantalla no los manda; estan para poder
    # forzar el comportamiento desde la API sin cambiar la configuracion.
    releer: bool | None = None
    incluir_pausados: bool | None = None
    solo_propios: bool | None = None


@app.post("/api/masivo")
async def masivo(data: MasivoIn):
    """Apaga (o prende) la carta entera de las plataformas que le pidas.

    Es el botón de cierre, y acepta UNA plataforma a propósito: a veces hay
    que apagar PedidosYa antes que Rappi.
    """
    try:
        return {"resultado": await cierre.ejecutar(
            worker, data.accion, data.plataformas,
            releer=data.releer,
            incluir_pausados=data.incluir_pausados,
            solo_propios=data.solo_propios)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/masivo/previo")
def masivo_previo(accion: str = "apagar_hoy"):
    """Cuántos productos tocaría cada plataforma, para avisar antes."""
    if accion not in cierre.ACCIONES:
        raise HTTPException(400, "accion invalida")
    return {"accion": accion, "por_plataforma": cierre.previo(
        config.plataformas_activas(), accion)}


@app.get("/api/alertas")
def alertas(db: Session = Depends(get_db)):
    """Lo que la app AFIRMA sin poder confirmarlo. Es lo que puede salir caro.

    El caso real (2026-07-28): el usuario apagó un producto, Todo-Selector lo
    mostró como «apagado hoy», y media hora después entró un pedido de
    PedidosYa con ese producto.

    El agujero: si la lectura de la carta no encuentra un producto (porque
    el nombre del catálogo no coincide con el del portal, o porque no se
    pudo abrir la categoría), la app **no pisa** el estado que tenía. Eso
    está bien —una lectura mala no debería borrar lo que sabíamos— pero el
    efecto es que un «apagado» viejo queda congelado y la pantalla lo sigue
    afirmando en presente mientras el portal lo vende.

    Acá salen los dos casos en que eso pasa:
      - la última lectura NO vio el producto en el portal;
      - hace mucho que nadie lo confirma.

    Solo importan los que la app da por apagados: si dice «prendido» y en
    realidad está apagado, se pierde una venta; al revés se vende algo que
    no hay.
    """
    # Dos rondas sin confirmar ya es raro: la ronda es cada 15 min.
    minutos = config.entero("minutos_ronda")
    limite = (datetime.now() - timedelta(minutes=max(minutos, 5) * 2)
              if minutos > 0 else None)

    # Lo que la ultima lectura no encontro, indexado para cruzarlo abajo.
    ciegos = {}
    for lista in worker.no_encontrados.values():
        for n in lista:
            ciegos[(n["producto_id"], n["plataforma"])] = n

    salida = []
    productos = (db.query(Producto)
                 .filter(Producto.activo == True)  # noqa: E712
                 .order_by(Producto.orden).all())

    for p in productos:
        if p.pausado:
            continue                     # el usuario ya dijo que no le importa
        for est in p.estados:
            if est.estado not in EstadoItem.APAGADOS_PROPIOS:
                continue

            no_visto = (p.id, est.plataforma) in ciegos
            viejo = (limite is not None and
                     (est.verificado_en is None or est.verificado_en < limite))
            if not (no_visto or viejo):
                continue

            salida.append({
                "producto_id": p.id,
                "producto": p.nombre,
                "plataforma": est.plataforma,
                "nombre_remoto": catalogo.nombre_remoto(p, est.plataforma),
                "estado": est.estado,
                "verificado_en": (est.verificado_en.isoformat(timespec="seconds")
                                  if est.verificado_en else None),
                # El motivo cambia que hay que hacer: si el portal no lo
                # muestra, es el nombre; si solo esta viejo, es releer.
                "motivo": ("no_aparece" if no_visto else "sin_confirmar"),
            })

    return {
        "sesiones_caidas": [p for p, ok in worker.sesion_ok.items() if ok is False],
        "sin_confirmar": salida,
        # Apagado en una tienda de Rappi y prendido en la hermana. Es el
        # mismo tipo de problema que el de arriba —algo que se sigue
        # vendiendo cuando creias que no— pero por otro camino: acá la app
        # SÍ lo está viendo, y justamente por eso lo puede decir.
        "sin_espejo": catalogo.desparejos(db, config.plataformas_activas()),
    }


@app.get("/api/estado-sistema")
def estado_sistema(db: Session = Depends(get_db)):
    pendientes = (db.query(Operacion)
                  .filter(Operacion.estado.in_([Operacion.PENDIENTE,
                                                Operacion.EN_CURSO]))
                  .count())
    # Lo que necesita la pantalla para saber si esto es un primer arranque:
    # sin sucursal no hay a donde entrar, y sin catalogo no hay nada que
    # mostrar. Van juntos porque el orden importa: primero decir qué local
    # sos, después leer la carta.
    falta_sucursal = [
        plat for plat, claves in (
            ("pedidosya", ("pedidosya_menu_id",)),
            ("rappi", ("rappi_store_id", "rappi_brand_id")),
        )
        if not all(config.texto(c) for c in claves)
    ]

    return {
        "version": VERSION,
        "simulado": MODO_SIMULADO,
        "arrancado_en": ARRANCADO_EN.isoformat(timespec="seconds"),
        "sesiones": worker.sesion_ok,
        # Las que esta instalación usa de verdad. La pantalla dibuja los
        # chips y los botones de «Apagar todo» con ESTO y no con una lista
        # fija: una plataforma opcional que nadie configuró no tiene por qué
        # aparecerle a nadie.
        "plataformas": config.plataformas_activas(),
        # Estado de la TIENDA entera (abierta/cerrada), no de un producto.
        # None de valor en el dict = todavia no se leyo o esta plataforma no
        # tiene el dato que hace falta (ver worker.estado_tienda). No
        # confundir con "falta_sucursal": esto es solo lectura.
        "tiendas": worker.estado_tiendas,
        "falta_sucursal": falta_sucursal,
        "catalogo_vacio": db.query(Producto).count() == 0,
        "operaciones_pendientes": pendientes,
        "ultimo_chequeo": (worker.ultimo_chequeo.isoformat()
                           if worker.ultimo_chequeo else None),
        "ultima_lectura": (worker.ultima_lectura.isoformat(timespec="seconds")
                           if worker.ultima_lectura else None),
    }


@app.post("/api/sincronizar-estado")
async def sincronizar_estado(plataforma: str = None):
    """Lee los portales y guarda cómo está cada producto ahora mismo.

    Se corre solo al arrancar. El botón sirve para cuando alguien apagó
    algo desde el portal y querés que la pantalla se entere.
    """
    return {"resultado": await worker.sincronizar_estados(plataforma)}


@app.post("/api/revalidar-sesion")
async def revalidar_sesion(plataforma: str = None):
    """Refresca las pestañas y rechequea el login.

    Util cuando Rappi te deslogueo o PedidosYa quedo con la pagina vieja.
    """
    sesiones = await worker.revalidar_sesion(plataforma)
    return {"sesiones": sesiones}


@app.get("/api/buscar-texto")
async def buscar_texto(plataforma: str, fragmento: str):
    """Diagnostico: como esta escrito realmente un producto en el portal.

    Ej: /api/buscar-texto?plataforma=rappi&fragmento=Tarta
    """
    return await worker.buscar_textos(plataforma, fragmento)


@app.get("/api/nombres")
async def nombres(plataforma: str):
    """Diagnostico: la carta tal como la muestra el portal ahora.

    Ej: /api/nombres?plataforma=pedidosya
    """
    return await worker.listar_productos(plataforma)


@app.get("/api/estructura")
async def estructura(plataforma: str):
    """Diagnostico: donde vive la navegacion de categorias de la pantalla.

    Ej: /api/estructura?plataforma=pedidosya
    """
    return await worker.estructura(plataforma)


@app.get("/api/carta")
async def carta(releer: bool = True):
    """Lee la carta de las dos plataformas y propone el emparejamiento.

    No modifica nada: es la propuesta para revisar. Reemplaza el catálogo
    escrito a mano de app/seed.py.

    Con `releer=false` devuelve la última lectura guardada en vez de ir a
    los portales, que tarda como un minuto. Es lo que usa la pantalla al
    abrirse: recargar el navegador no tiene por qué costar otra lectura.
    """
    carta = await worker.leer_carta(releer=releer)
    if carta is None:
        return {"sin_lectura": True}
    return carta


@app.get("/api/esqueleto")
async def esqueleto(plataforma: str):
    """Diagnostico: el arbol del DOM de la pantalla del menu.

    Ej: /api/esqueleto?plataforma=pedidosya
    """
    return await worker.esqueleto(plataforma)


@app.get("/api/estado-tienda")
async def estado_tienda(plataforma: str):
    """Fuerza releer si la TIENDA (no un producto) esta abierta o cerrada.

    Ej: /api/estado-tienda?plataforma=rappi
    Sirve para probar rappi_nombre_tienda / rappi_comun_nombre_tienda recien
    cargados en Ajustes sin esperar a la proxima ronda de reverificacion.

    Si no se pudo confirmar, devuelve "abierta": null CON el motivo y un
    diagnostico (que textos habia en la pantalla, cuantas tiendas se veian).
    Un "no se" mudo no distingue "el selector no encontro nada" de "falta un
    dato en Ajustes", que son arreglos distintos: eso fue exactamente lo que
    dejo el badge de las dos tiendas de Rappi en "sin datos" sin pista
    ninguna (2026-07-30).
    """
    resultado = await worker.estado_tienda(plataforma)
    worker.estado_tiendas[plataforma] = resultado
    return resultado


@app.get("/api/verificar-catalogo")
async def verificar_catalogo(plataforma: str):
    """Diagnostico: busca toda la carta en el portal y dice que no coincide.

    Ej: /api/verificar-catalogo?plataforma=rappi
    """
    return await worker.verificar_catalogo(plataforma)


@app.get("/api/diagnostico")
async def diagnostico(plataforma: str, nombre: str):
    """Diagnostico: prueba leer un producto por nombre exacto, sin tocar nada.

    Ej: /api/diagnostico?plataforma=pedidosya&nombre=Tarta%20de%20verdura
    """
    return await worker.diagnosticar(plataforma, nombre)


@app.get("/api/historial")
def historial(limite: int = 50, db: Session = Depends(get_db)):
    ops = (db.query(Operacion)
           .order_by(Operacion.creada_en.desc())
           .limit(limite)
           .all())
    return [{
        "id": o.id,
        "producto": o.producto.nombre if o.producto else "?",
        "plataforma": o.plataforma,
        "accion": o.accion,
        "estado": o.estado,
        "intentos": o.intentos,
        "detalle": o.detalle,
        "creada_en": o.creada_en.isoformat() if o.creada_en else None,
    } for o in ops]


class VincularIn(BaseModel):
    # El par de siempre. Se pueden mandar así, o en `nombres`, que acepta
    # cualquier combinación de plataformas: la pantalla de asociación manda
    # las tres cuando el local tiene las dos tiendas de Rappi.
    pedidosya: str | None = None     # nombre tal cual figura en ese portal
    rappi: str | None = None
    nombres: dict[str, str] | None = None
    nombre: str | None = None        # canonico, si querés uno distinto
    categoria: str = ""

    def todos(self) -> dict:
        """Las plataformas a vincular, vengan como vengan."""
        junto = dict(self.nombres or {})
        if self.pedidosya:
            junto.setdefault("pedidosya", self.pedidosya)
        if self.rappi:
            junto.setdefault("rappi", self.rappi)
        return {plat: remoto for plat, remoto in junto.items() if remoto}


class SepararIn(BaseModel):
    producto_id: int
    plataforma: str


class AgregarIn(BaseModel):
    plataforma: str
    nombre_remoto: str
    categoria: str = ""


def _ver_producto(p) -> dict:
    return {
        "id": p.id,
        "nombre": p.nombre,
        "categoria": p.categoria,
        "plataformas": {plat: catalogo.nombre_remoto(p, plat)
                        for plat in catalogo.PLATAFORMAS},
    }


@app.post("/api/vincular")
def vincular(data: VincularIn, db: Session = Depends(get_db)):
    """Esos nombres pasan a ser el mismo producto: un solo botón.

    Es la respuesta a "dejame linkear opciones al mismo botón de apagado".
    Fusiona si ya estaban cargados por separado. Acepta dos plataformas o
    las que sean: con las dos tiendas de Rappi son tres.
    """
    nombres = data.todos()

    desconocidas = [p for p in nombres if p not in config.plataformas_activas()]
    if desconocidas:
        raise HTTPException(400, f"{desconocidas[0]} no está activa en esta "
                                 f"instalación")
    try:
        producto = catalogo.vincular_varios(db, nombres, nombre=data.nombre,
                                            categoria=data.categoria)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()

    # Si esto venía de un aviso, ya está resuelto: que no siga apareciendo.
    vinculados = set(nombres.values())
    for plataforma, lista in worker.novedades.items():
        worker.novedades[plataforma] = [
            n for n in lista if n["nombre_en_el_portal"] not in vinculados
        ]

    return {"ok": True, "producto": _ver_producto(producto)}


class EnlazarIn(BaseModel):
    producto_id: int
    plataforma: str
    nombre_remoto: str


@app.post("/api/enlazar")
def enlazar(data: EnlazarIn, db: Session = Depends(get_db)):
    """Suma una plataforma a un producto que YA existe (no crea uno nuevo).

    Es lo que usa el aviso de "novedad" cuando la plataforma no es una de
    las dos principales (PedidosYa/Rappi) — hoy, Rappi Común: un plato que
    ya se apaga en las otras dos y ahora también hay que apagarlo ahí.
    """
    if data.plataforma not in config.plataformas_activas():
        raise HTTPException(400, f"{data.plataforma} no está activa en esta "
                                 f"instalación")
    try:
        producto = catalogo.enlazar(db, data.producto_id, data.plataforma,
                                    data.nombre_remoto)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()

    for plataforma, lista in worker.novedades.items():
        worker.novedades[plataforma] = [
            n for n in lista
            if not (n["plataforma"] == data.plataforma
                    and n["nombre_en_el_portal"] == data.nombre_remoto)
        ]

    return {"ok": True, "producto": _ver_producto(producto)}


@app.post("/api/separar")
def separar(data: SepararIn, db: Session = Depends(get_db)):
    """Saca una plataforma del producto y la deja como producto aparte."""
    try:
        nuevo = catalogo.separar(db, data.producto_id, data.plataforma)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return {"ok": True, "producto": _ver_producto(nuevo)}


@app.post("/api/agregar")
def agregar(data: AgregarIn, db: Session = Depends(get_db)):
    """Carga un producto que existe en una sola plataforma."""
    try:
        producto = catalogo.agregar(db, data.plataforma, data.nombre_remoto,
                                    categoria=data.categoria)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return {"ok": True, "producto": _ver_producto(producto)}


class PausaIn(BaseModel):
    producto_id: int
    pausado: bool


@app.post("/api/pausar")
def pausar(data: PausaIn, db: Session = Depends(get_db)):
    """Marca un producto como temporalmente inactivo (o lo reactiva).

    Sigue en la carta del portal, pero este mes no se vende: se va al final
    de la pantalla, apagado de color, y la ronda de cada 15 minutos deja de
    sostenerlo. El estado se lo sigue leyendo, que sale gratis porque la
    lectura trae la carta entera igual.
    """
    producto = db.query(Producto).get(data.producto_id)
    if producto is None:
        raise HTTPException(404, "producto no encontrado")

    producto.pausado = data.pausado
    db.commit()
    return {"ok": True, "pausado": producto.pausado}


class IgnorarIn(BaseModel):
    plataforma: str
    nombre_remoto: str


@app.get("/api/novedades")
def novedades():
    """Productos del catálogo que aparecieron en un portal donde no estaban.

    Sale de la lectura del estado real: si algo figuraba como "no existe en
    PedidosYa" y el portal ahora lo muestra, es que lo agregaste a la carta.
    """
    salida = []
    for lista in worker.novedades.values():
        salida.extend(lista)
    return {"novedades": salida}


@app.post("/api/novedades/ignorar")
def ignorar_novedad(data: IgnorarIn, db: Session = Depends(get_db)):
    """No avisar más de este nombre."""
    catalogo.ignorar_novedad(db, data.plataforma, data.nombre_remoto)
    db.commit()

    for plataforma, lista in worker.novedades.items():
        worker.novedades[plataforma] = [
            n for n in lista
            if not (n["plataforma"] == data.plataforma
                    and n["nombre_en_el_portal"] == data.nombre_remoto)
        ]
    return {"ok": True}


class RenombrarIn(BaseModel):
    producto_id: int
    nombre: str


@app.post("/api/renombrar")
def renombrar(data: RenombrarIn, db: Session = Depends(get_db)):
    """Cambia el nombre con el que se ve el producto en la pantalla.

    No toca los nombres de los portales: esos son los alias, y son los que
    se usan para buscarlo. Sirve para limpiar los nombres que quedan feos
    cuando dos productos se llamaban igual y hubo que desempatarlos.
    """
    producto = db.query(Producto).get(data.producto_id)
    if producto is None:
        raise HTTPException(404, "producto no encontrado")

    nombre = data.nombre.strip()
    if not nombre:
        raise HTTPException(400, "el nombre no puede quedar vacío")

    otro = db.query(Producto).filter_by(nombre=nombre).first()
    if otro is not None and otro.id != producto.id:
        raise HTTPException(400, f"ya hay un producto que se llama «{nombre}»")

    catalogo.guardar_paso(db, f"renombrar '{producto.nombre}' a '{nombre}'")
    producto.nombre = nombre
    catalogo.marcar_manual(db)
    db.commit()
    return {"ok": True, "producto": _ver_producto(producto)}


@app.post("/api/deshacer")
def deshacer(db: Session = Depends(get_db)):
    """Vuelve el catálogo a como estaba antes del último cambio."""
    descripcion = catalogo.deshacer(db)
    if descripcion is None:
        raise HTTPException(400, "no hay nada para deshacer")
    db.commit()
    return {"ok": True, "deshecho": descripcion,
            "siguiente": catalogo.hay_para_deshacer(db)}


@app.get("/api/catalogo")
def ver_catalogo(db: Session = Depends(get_db)):
    """Qué nombre tiene cada producto en cada portal, y quién manda.

    La pantalla Carta lo cruza con lo que leen los portales para saber qué
    está vinculado, qué está suelto y qué no está cargado.
    """
    productos = (db.query(Producto)
                 .filter(Producto.activo == True)  # noqa: E712
                 .order_by(Producto.orden).all())
    return {
        "manual": catalogo.es_manual(db),
        "deshacer": catalogo.hay_para_deshacer(db),
        "productos": [_ver_producto(p) for p in productos],
    }


class ConfigIn(BaseModel):
    cambios: dict


@app.get("/api/config")
def ver_config():
    """Los ajustes con su definicion: la pantalla los dibuja de acá.

    Devuelve tipo, ayuda, límites y valor actual de cada uno, así agregar un
    ajuste nuevo es agregarlo a `config.OPCIONES` y nada más.
    """
    return {"opciones": config.para_la_pantalla()}


@app.post("/api/config")
async def guardar_config(data: ConfigIn, db: Session = Depends(get_db)):
    """Guarda los ajustes y los aplica sin reiniciar la app."""
    try:
        config.guardar(db, data.cambios)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()

    config.recargar()
    await worker.aplicar_config()
    return {"ok": True, "opciones": config.para_la_pantalla()}


@app.post("/api/config/restablecer")
async def restablecer_config(db: Session = Depends(get_db)):
    """Vuelve todos los ajustes a los valores por defecto."""
    config.restablecer(db)
    db.commit()

    config.recargar()
    await worker.aplicar_config()
    return {"ok": True, "opciones": config.para_la_pantalla()}


@app.post("/api/alias")
def guardar_alias(data: AliasIn, db: Session = Depends(get_db)):
    alias = (db.query(AliasPlataforma)
             .filter_by(producto_id=data.producto_id, plataforma=data.plataforma)
             .first())
    if alias is None:
        alias = AliasPlataforma(producto_id=data.producto_id,
                                plataforma=data.plataforma)
        db.add(alias)
    alias.nombre_remoto = data.nombre_remoto
    db.commit()
    return {"ok": True}


# ---------- Frontend ----------

app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


# La app se autoactualiza, asi que el navegador NO puede cachear la pantalla:
# quedaba con el HTML viejo despues de cada update y mostraba estados que esa
# version no sabia nombrar ("apagado_ajeno" crudo en vez de "apagado (afuera)",
# 2026-07-28). Con no-store, abrir la pagina siempre trae la version que
# corresponde al server que la esta sirviendo.
SIN_CACHE = {"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"}


ICONO = RAIZ / "todo2.ico"


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """El icono de la pestaña. Chrome lo pide solo, sin que la pagina lo pida.

    Se sirve desde la raiz del repo y no desde static/ porque el mismo
    archivo lo usa el acceso directo del escritorio (ver actualizar.ps1).
    """
    if not ICONO.exists():
        raise HTTPException(404, "no hay icono")
    return FileResponse(str(ICONO), media_type="image/x-icon")


@app.get("/")
def index():
    return FileResponse(str(STATIC / "index.html"), headers=SIN_CACHE)


# Ajustes y Carta son pantallas propias (URL propia via history.pushState,
# no un panel que se despliega arriba del dashboard -- ver mostrarPantalla()
# en index.html), pero siguen siendo el mismo archivo. Estas rutas son solo
# para que un F5 (o abrir el link a mano) no tire 404: sirven el mismo
# index.html, que arranca mostrando el dashboard (no reabre la pantalla
# sola). Navegar ahi con los botones de la app sigue andando igual.
@app.get("/ajustes")
@app.get("/carta")
def pantalla_spa():
    return FileResponse(str(STATIC / "index.html"), headers=SIN_CACHE)
