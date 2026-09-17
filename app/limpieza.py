"""Archivar copias exactas del catálogo, sin operar los portales."""
import hashlib
import json
from . import catalogo
from .models import Producto, Operacion, EstadoItem, HistorialCatalogo


def _mapa(p):
    return {plat: catalogo.nombre_remoto(p, plat) for plat in catalogo.PLATAFORMAS
            if catalogo.nombre_remoto(p, plat) is not None}


def _fila(p):
    return {"id": p.id, "nombre": p.nombre, "categoria": p.categoria,
            "pausado": p.pausado, "plataformas": _mapa(p),
            "estados": {e.plataforma: e.estado for e in p.estados}}


def _rango(p):
    conocidos = sum(e.verificado_en is not None and e.estado not in
                   (EstadoItem.DESCONOCIDO, EstadoItem.FALLO) for e in p.estados)
    return (len(_mapa(p)), conocidos, bool(p.categoria_manual),
            bool(p.categoria), -p.id)


def planificar(db):
    productos = db.query(Producto).filter_by(activo=True).order_by(Producto.id).all()
    por_id = {p.id: p for p in productos}
    vecinos = {p.id: set() for p in productos}
    dueños = {}
    for p in productos:
        for clave in _mapa(p).items():
            for otro in dueños.get(clave, []):
                vecinos[p.id].add(otro)
                vecinos[otro].add(p.id)
            dueños.setdefault(clave, []).append(p.id)
    vivas = db.query(Operacion).filter(Operacion.estado.in_(Operacion.VIVAS)).all()
    ocupados = {op.producto_id for op in vivas}
    grupos, revisar, vistos = [], [], set()
    for pid in por_id:
        if pid in vistos or not vecinos[pid]:
            continue
        pendientes, ids = [pid], set()
        while pendientes:
            actual = pendientes.pop()
            if actual in ids:
                continue
            ids.add(actual)
            pendientes.extend(vecinos[actual] - ids)
        vistos.update(ids)
        miembros = [por_id[i] for i in sorted(ids)]
        mapas = [_mapa(p) for p in miembros]
        nombres = {plat: {m[plat] for m in mapas if plat in m}
                   for plat in catalogo.PLATAFORMAS}
        motivo = None
        if any(len(n) > 1 for n in nombres.values()):
            motivo = "Comparten un nombre, pero tienen vínculos distintos en otro portal."
        elif len({p.pausado for p in miembros}) > 1:
            motivo = "Algunas filas están pausadas y otras no."
        elif len({p.categoria for p in miembros if p.categoria_manual}) > 1:
            motivo = "Tienen categorías manuales diferentes."
        elif ids & ocupados:
            motivo = "Hay operaciones en cola o en curso: esperá o cancelalas antes de limpiar."
        union = {plat: next(iter(n)) for plat, n in nombres.items() if len(n) == 1}
        candidatos = [p for p in miembros if _mapa(p) == union]
        if not motivo and not candidatos:
            motivo = "Ninguna fila reúne todos los vínculos; revisalos en Vincular a mano."
        if motivo:
            revisar.append({"filas": [_fila(p) for p in miembros], "motivo": motivo})
            continue
        destino = max(candidatos, key=_rango)
        grupos.append({"conservar": _fila(destino),
                       "archivar": [_fila(p) for p in miembros if p.id != destino.id]})
    # Incluye estados, pausas, vínculos y cola. Una pantalla vieja no autoriza
    # una limpieza distinta de la que el usuario acaba de revisar.
    material = {"catalogo": catalogo._foto(db),
                "vivas": sorted((o.id, o.producto_id, o.estado) for o in vivas)}
    firma = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    return {"firma": firma, "grupos": grupos, "revisar": revisar,
            "total": sum(len(g["archivar"]) for g in grupos)}


def ejecutar(db, firma):
    plan = planificar(db)
    if firma != plan["firma"]:
        raise ValueError("El catálogo o la cola cambiaron. Volvé a revisar los duplicados.")
    if not plan["total"]:
        return {"archivados": 0}
    catalogo.guardar_paso(db, "limpiar duplicados")
    afectados = {p["id"] for g in plan["grupos"]
                 for p in [g["conservar"]] + g["archivar"]}
    paso = db.query(HistorialCatalogo).order_by(HistorialCatalogo.id.desc()).first()
    paso.datos = json.dumps({"tipo": "limpieza_duplicados",
                            "productos": [p for p in json.loads(paso.datos)
                                          if p["id"] in afectados]}, ensure_ascii=False)
    for grupo in plan["grupos"]:
        destino = db.get(Producto, grupo["conservar"]["id"])
        copias = [db.get(Producto, p["id"]) for p in grupo["archivar"]]
        todos = [destino] + copias
        manual = next((p for p in todos if p.categoria_manual), None)
        if manual:
            destino.categoria = manual.categoria
            destino.categoria_manual = True
        elif not destino.categoria:
            destino.categoria = next((p.categoria for p in todos if p.categoria), "")
        for est in destino.estados:
            otras = [e for p in todos for e in p.estados
                     if e.plataforma == est.plataforma]
            informadas = [e for e in otras if e.estado != EstadoItem.DESCONOCIDO]
            valores = {e.estado for e in informadas}
            categoria = next((e.categoria_portal for e in otras if e.categoria_portal), "")
            if len(valores) == 1 and EstadoItem.FALLO not in valores:
                est.estado = informadas[0].estado
                fechas = [e.verificado_en for e in informadas if e.verificado_en]
                est.verificado_en = max(fechas) if fechas else None
                est.detalle = ""
            else:
                est.estado = EstadoItem.DESCONOCIDO
                est.verificado_en = None
                est.detalle = "falta releer el portal después de limpiar duplicados"
            if not est.categoria_portal:
                est.categoria_portal = categoria
        for copia in copias:
            # Se conserva el id, historial, alias y estados: deshacer restaura
            # activo=True. No remapear intenciones viejas a la fila conservada.
            copia.activo = False
    catalogo.marcar_manual(db)
    db.flush()
    return {"archivados": plan["total"]}


def deshacer(db, paso, datos):
    """Reactivar las filas, sin restaurar estados antiguos sobre lecturas nuevas."""
    for anterior in datos["productos"]:
        p = db.get(Producto, anterior["id"])
        if p is None:
            raise ValueError("El catálogo cambió: no se puede deshacer esta limpieza.")
        for campo in ("activo", "categoria", "categoria_manual", "orden", "pausado"):
            setattr(p, campo, anterior.get(campo, False if campo == "categoria_manual" else None))
    descripcion = paso.descripcion
    db.delete(paso)
    return descripcion
