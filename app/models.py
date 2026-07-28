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
    categoria = Column(String(60), default="")   # Platos, Tartas, Bebidas...
    orden = Column(Integer, default=0)
    activo = Column(Boolean, default=True)       # False = no lo mostramos en la UI

    # Temporalmente inactivo: sigue en la carta del portal pero este mes no
    # se vende. Se muestra al final y apagado de color, y la ronda de cada
    # 15 min NO lo sostiene: si figura apagado, se queda apagado sin que la
    # app lo ande reencolando. Sirve para que lo que no se toca no estorbe.
    pausado = Column(Boolean, default=False)

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

    En Rappi algunos nombres difieren (ej: 'Ensalada mixta de hojas' vs 'Ensalada mixta').
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

    # Apagado en el portal, pero no por la app: lo leimos asi. Se distingue
    # de los otros dos apagados A PROPOSITO. La ronda de reverificacion
    # reencola un apagado cuando ve "revivido" algo que ella apago, y no
    # queremos que se apropie de todo lo que el local apago por su cuenta:
    # bastaria una lectura mala para que lo vuelva a apagar sin que nadie
    # se lo haya pedido.
    APAGADO_AJENO = "apagado_ajeno"

    # Los que la app impuso ella misma, y por lo tanto sostiene.
    APAGADOS_PROPIOS = (APAGADO_HOY, APAGADO_INDEF)
    # Mientras hay una operacion en curso, lo que diga el portal es
    # transitorio: no lo pisamos con una lectura.
    EN_CURSO = (APAGANDO, PRENDIENDO)

    id = Column(Integer, primary_key=True)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    plataforma = Column(String(20), nullable=False)

    estado = Column(String(30), default=DESCONOCIDO)
    detalle = Column(Text, default="")            # mensaje de error si fallo
    verificado_en = Column(DateTime, nullable=True)
    actualizado_en = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    producto = relationship("Producto", back_populates="estados")


class Preferencia(Base):
    """Clave/valor suelto. Hoy guarda si ya se preguntaron los platos del dia.

    Hace falta porque "hoy no hay platos" es una respuesta valida que no crea
    ningun Producto: sin esta marca, la app volvia a preguntar en cada recarga.
    """
    __tablename__ = "preferencias"

    PLATOS_RESPONDIDO = "platos_dia_respondido"   # valor = fecha YYYY-MM-DD

    # "1" = el catalogo lo maneja el usuario desde la app (vinculo/separo
    # productos), asi que seed.py deja de pisar los alias en cada arranque.
    CATALOGO_MANUAL = "catalogo_manual"

    # Nombres que aparecieron en un portal y el usuario NO quiso vincular.
    # Lista JSON de "plataforma|nombre". Sin esto, el aviso volvia en cada
    # arranque y terminabas ignorandolo.
    NOVEDADES_IGNORADAS = "novedades_ignoradas"

    clave = Column(String(60), primary_key=True)
    valor = Column(String(200), default="")


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
