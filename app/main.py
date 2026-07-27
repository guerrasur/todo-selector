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
    }


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

    Ej: /api/buscar-texto?plataforma=rappi&fragmento=Gaseosa
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

    Ej: /api/diagnostico?plataforma=pedidosya&nombre=Gaseosa%20Cola
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


@app.get("/")
def index():
    return FileResponse(str(STATIC / "index.html"))
