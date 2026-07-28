"""API + frontend de Todo-Selector."""

import logging
import os
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import catalogo
from .database import init_db, get_db
from .models import Producto, AliasPlataforma, EstadoItem, Operacion, Preferencia
from .seed import sembrar
from .worker import worker

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Todo-Selector")

RAIZ = Path(__file__).resolve().parent.parent
STATIC = RAIZ / "static"

MODO_SIMULADO = os.environ.get("STOCKSWITCH_SIMULADO", "0") == "1"

# El .bat actualiza ANTES de levantar el server: si la ventana queda abierta,
# segui corriendo el codigo viejo aunque los archivos ya esten nuevos. Esto
# lo hace visible en vez de que se note como un 404 raro.
ARRANCADO_EN = datetime.now()


@app.on_event("startup")
async def arrancar():
    init_db()
    sembrar()
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
    hoy = date.today().isoformat()
    productos = (
        db.query(Producto)
        .filter(Producto.activo == True)  # noqa: E712
        .order_by(Producto.orden)
        .all()
    )
    # Los platos del dia solo se muestran si son de hoy
    productos = [p for p in productos
                 if not p.es_plato_del_dia or p.fecha_dia == hoy]

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

    if data.accion not in ("apagar_hoy", "apagar_indef", "prender"):
        raise HTTPException(400, "accion invalida")

    creadas = []
    for plat in data.plataformas:
        op = Operacion(
            producto_id=data.producto_id,
            plataforma=plat,
            accion=data.accion,
        )
        db.add(op)

        # Marcamos estado transitorio para feedback inmediato en la UI
        est = (db.query(EstadoItem)
               .filter_by(producto_id=data.producto_id, plataforma=plat)
               .first())
        if est:
            est.estado = (EstadoItem.PRENDIENDO if data.accion == "prender"
                          else EstadoItem.APAGANDO)

        creadas.append(plat)

    db.commit()
    return {"encoladas": creadas}


@app.get("/api/estado-sistema")
def estado_sistema(db: Session = Depends(get_db)):
    pendientes = (db.query(Operacion)
                  .filter(Operacion.estado.in_([Operacion.PENDIENTE,
                                                Operacion.EN_CURSO]))
                  .count())
    return {
        "simulado": MODO_SIMULADO,
        "arrancado_en": ARRANCADO_EN.isoformat(timespec="seconds"),
        "sesiones": worker.sesion_ok,
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


class PlatoDiaIn(BaseModel):
    nombres: list[str]               # nombres canonicos de los platos de hoy
    alias_rappi: dict[str, str] = {} # nombre -> como se llama en Rappi


@app.get("/api/platos-del-dia")
def obtener_platos_dia(db: Session = Depends(get_db)):
    """Devuelve los platos cargados para hoy, y si ya se preguntó."""
    hoy = date.today().isoformat()
    platos = (db.query(Producto)
              .filter(Producto.es_plato_del_dia == True,  # noqa: E712
                      Producto.fecha_dia == hoy)
              .all())
    marca = db.query(Preferencia).get(Preferencia.PLATOS_RESPONDIDO)
    return {
        "fecha": hoy,
        "ya_cargados": len(platos) > 0,
        # "Hoy no hay" es una respuesta valida: sin esta marca la app
        # volvia a preguntar en cada recarga.
        "ya_respondido": bool(marca and marca.valor == hoy),
        "platos": [p.nombre for p in platos],
    }


@app.post("/api/platos-del-dia")
def guardar_platos_dia(data: PlatoDiaIn, db: Session = Depends(get_db)):
    """Carga los platos de hoy. Los de dias anteriores se desactivan."""
    hoy = date.today().isoformat()

    # Bajamos los platos del dia viejos
    (db.query(Producto)
     .filter(Producto.es_plato_del_dia == True,  # noqa: E712
             Producto.fecha_dia != hoy)
     .update({"activo": False}, synchronize_session=False))

    for nombre in data.nombres:
        nombre = nombre.strip()
        if not nombre:
            continue

        p = db.query(Producto).filter_by(nombre=nombre).first()
        if p is None:
            p = Producto(nombre=nombre, categoria="Plato del día", orden=900)
            db.add(p)
            db.flush()
            for plat in ("pedidosya", "rappi"):
                db.add(EstadoItem(producto_id=p.id, plataforma=plat,
                                  estado=EstadoItem.DESCONOCIDO))

        p.es_plato_del_dia = True
        p.fecha_dia = hoy
        p.activo = True

        alias_r = data.alias_rappi.get(nombre)
        if alias_r:
            al = (db.query(AliasPlataforma)
                  .filter_by(producto_id=p.id, plataforma="rappi").first())
            if al is None:
                al = AliasPlataforma(producto_id=p.id, plataforma="rappi")
                db.add(al)
            al.nombre_remoto = alias_r

    marca = db.query(Preferencia).get(Preferencia.PLATOS_RESPONDIDO)
    if marca is None:
        marca = Preferencia(clave=Preferencia.PLATOS_RESPONDIDO)
        db.add(marca)
    marca.valor = hoy

    db.commit()
    return {"ok": True, "fecha": hoy}


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

    Ej: /api/buscar-texto?plataforma=rappi&fragmento=Coca
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


@app.get("/api/verificar-catalogo")
async def verificar_catalogo(plataforma: str):
    """Diagnostico: busca toda la carta en el portal y dice que no coincide.

    Ej: /api/verificar-catalogo?plataforma=rappi
    """
    return await worker.verificar_catalogo(plataforma)


@app.get("/api/diagnostico")
async def diagnostico(plataforma: str, nombre: str):
    """Diagnostico: prueba leer un producto por nombre exacto, sin tocar nada.

    Ej: /api/diagnostico?plataforma=pedidosya&nombre=Coca%20Cola
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
    pedidosya: str                   # nombre tal cual figura en ese portal
    rappi: str
    nombre: str | None = None        # canonico, si querés uno distinto
    categoria: str = ""


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
    """Los dos nombres pasan a ser el mismo producto: un solo botón.

    Es la respuesta a "dejame linkear opciones al mismo botón de apagado".
    Fusiona si ya estaban cargados por separado.
    """
    try:
        producto = catalogo.vincular(db, data.pedidosya, data.rappi,
                                     nombre=data.nombre, categoria=data.categoria)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()

    # Si esto venía de un aviso, ya está resuelto: que no siga apareciendo.
    for plataforma, lista in worker.novedades.items():
        worker.novedades[plataforma] = [
            n for n in lista
            if n["nombre_en_el_portal"] not in (data.pedidosya, data.rappi)
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
