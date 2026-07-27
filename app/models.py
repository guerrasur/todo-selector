"""Modelos de la base. Un producto puede llamarse distinto en cada plataforma."""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text, UniqueConstraint
)
from sqlalchemy.orm import relationship

from .database import Base


class Producto(Base):
    """Nombre canonico del producto (el que usas vos)."""
    __tablename__ = "productos"

    id = Column(Integer, primary_key=True)
    nombre = Column(String(120), nullable=False, unique=True)
    categoria = Column(String(60), default="")   # Ensaladas, Wraps, Bebidas...
    orden = Column(Integer, default=0)
    activo = Column(Boolean, default=True)       # False = no lo mostramos en la UI

    # Platos del dia: cambian a diario, se cargan al inicio de la jornada.
    # 'fecha_dia' guarda para que dia son; si no es hoy, no se muestran.
    es_plato_del_dia = Column(Boolean, default=False)
    fecha_dia = Column(String(10), default="")   # YYYY-MM-DD

    alias = relationship("AliasPlataforma", back_populates="producto",
                         cascade="all, delete-orphan")
    estados = relationship("EstadoItem", back_populates="producto",
                           cascade="all, delete-orphan")


class AliasPlataforma(Base):
    """Como se llama ese producto en cada plataforma.

    En Rappi algunos nombres difieren (ej: 'Risotto de Hongos' vs 'Risotto').
    Si no hay alias cargado, se usa el nombre canonico.
    """
    __tablename__ = "alias_plataforma"
    __table_args__ = (UniqueConstraint("producto_id", "plataforma"),)

    id = Column(Integer, primary_key=True)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    plataforma = Column(String(20), nullable=False)   # 'rappi' | 'pedidosya'
    nombre_remoto = Column(String(160), nullable=False)

    producto = relationship("Producto", back_populates="alias")


class EstadoItem(Base):
    """Estado actual del producto en una plataforma."""
    __tablename__ = "estados_item"
    __table_args__ = (UniqueConstraint("producto_id", "plataforma"),)

    # Estados posibles
    PRENDIDO = "prendido"
    APAGANDO = "apagando"
    PRENDIENDO = "prendiendo"
    APAGADO_HOY = "apagado_hoy"
    APAGADO_INDEF = "apagado_indefinido"
    FALLO = "fallo"
    DESCONOCIDO = "desconocido"

    id = Column(Integer, primary_key=True)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    plataforma = Column(String(20), nullable=False)

    estado = Column(String(30), default=DESCONOCIDO)
    detalle = Column(Text, default="")            # mensaje de error si fallo
    verificado_en = Column(DateTime, nullable=True)
    actualizado_en = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    producto = relationship("Producto", back_populates="estados")


class Operacion(Base):
    """Cola de trabajo + historial. El worker toma las pendientes."""
    __tablename__ = "operaciones"

    PENDIENTE = "pendiente"
    EN_CURSO = "en_curso"
    OK = "ok"
    ERROR = "error"

    id = Column(Integer, primary_key=True)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    plataforma = Column(String(20), nullable=False)

    accion = Column(String(30), nullable=False)   # apagar_hoy | apagar_indef | prender
    estado = Column(String(20), default=PENDIENTE)
    intentos = Column(Integer, default=0)
    detalle = Column(Text, default="")

    creada_en = Column(DateTime, default=datetime.now)
    finalizada_en = Column(DateTime, nullable=True)

    producto = relationship("Producto")
