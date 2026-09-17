"""Identidad de la última intención y feedback de operaciones pendientes."""

from .models import EstadoItem, Operacion


def ultima(db, producto_id, plataforma):
    return (db.query(Operacion)
            .filter_by(producto_id=producto_id, plataforma=plataforma)
            .order_by(Operacion.id.desc()).first())


def ultima_id(db, producto_id, plataforma):
    op = ultima(db, producto_id, plataforma)
    return op.id if op else None


def reflejar_pendiente(db, producto_id, plataforma):
    """Una operación anterior no puede ocultar la nueva que espera detrás."""
    pendiente = (db.query(Operacion)
                 .filter(Operacion.producto_id == producto_id,
                         Operacion.plataforma == plataforma,
                         Operacion.estado.in_(Operacion.VIVAS))
                 .order_by(Operacion.id.desc()).first())
    est = (db.query(EstadoItem)
           .filter_by(producto_id=producto_id, plataforma=plataforma).first())
    if pendiente is not None and est is not None:
        est.estado = (EstadoItem.PRENDIENDO if pendiente.accion == "prender"
                      else EstadoItem.APAGANDO)
        est.detalle = ""
        return True
    if est is not None and est.estado in EstadoItem.EN_CURSO:
        est.estado = EstadoItem.DESCONOCIDO
        est.detalle = "sin operaciones pendientes; falta confirmar el portal"
    return False
