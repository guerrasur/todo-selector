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
    categoria = Column(String(60), default="")   # como las agrupes vos
    orden = Column(Integer, default=0)
    activo = Column(Boolean, default=True)       # False = no lo mostramos en la UI

    # Temporalmente inactivo: sigue en la carta del portal pero este mes no
    # se vende. Se muestra al final y apagado de color, y la ronda de cada
    # 15 min NO lo sostiene: si figura apagado, se queda apagado sin que la
    # app lo ande reencolando. Sirve para que lo que no se toca no estorbe.
    pausado = Column(Boolean, default=False)

    # OJO: la base puede tener todavia las columnas es_plato_del_dia y
    # fecha_dia, de cuando la app preguntaba los platos del dia. Se saco esa
    # pantalla (2026-07-28) y las columnas quedaron sin usar: son nullable,
    # asi que no molestan, y borrarlas no esta cubierto por la migracion.

    alias = relationship("AliasPlataforma", back_populates="producto",
                         cascade="all, delete-orphan")
    estados = relationship("EstadoItem", back_populates="producto",
                           cascade="all, delete-orphan")


class AliasPlataforma(Base):
    """Como se llama ese producto en cada plataforma.

    En Rappi algunos nombres difieren (ej: 'Ensalada mixta de hojas' vs
    'Ensalada mixta').
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
    """Clave/valor suelto para marcas sueltas de la app."""
    __tablename__ = "preferencias"

    # "1" = el catalogo lo maneja el usuario desde la app (vinculo/separo
    # productos), asi que seed.py deja de pisar los alias en cada arranque.
    CATALOGO_MANUAL = "catalogo_manual"

    # Nombres que aparecieron en un portal y el usuario NO quiso vincular.
    # Lista JSON de "plataforma|nombre". Sin esto, el aviso volvia en cada
    # arranque y terminabas ignorandolo.
    NOVEDADES_IGNORADAS = "novedades_ignoradas"

    # Los ajustes de la pantalla de configuracion viven aca tambien, con el
    # prefijo "cfg_" para no mezclarse con estas dos marcas. Ver app/config.py.

    clave = Column(String(60), primary_key=True)
    # Text y no String(200): NOVEDADES_IGNORADAS guarda una lista JSON que
    # crece con cada "No, es otro" y se pasaba de largo. SQLite no valida el
    # largo declarado, asi que el cambio no necesita migracion.
    valor = Column(Text, default="")


class HistorialCatalogo(Base):
    """Foto del catalogo ANTES de cada cambio, para poder deshacer.

    Vincular y separar tocan varios productos a la vez y no son faciles de
    revertir a mano: una vinculacion equivocada puede dejar sueltos a otros
    dos. Sin un "deshacer", un click desprolijo cuesta reconstruir el
    catalogo a mano. La foto es chica (30 productos) y solo se guardan las
    ultimas, asi que sale barato.
    """
    __tablename__ = "historial_catalogo"

    MAXIMO = 20      # cuantos pasos atras se pueden deshacer

    id = Column(Integer, primary_key=True)
    creada_en = Column(DateTime, default=datetime.now)
    descripcion = Column(String(300), default="")
    datos = Column(Text, default="")          # JSON con productos/alias/estados


class Operacion(Base):
    """Cola de trabajo + historial. El worker toma las pendientes."""
    __tablename__ = "operaciones"

    PENDIENTE = "pendiente"
    EN_CURSO = "en_curso"
    OK = "ok"
    ERROR = "error"
    # La saco el usuario de la cola a mano. NO es un error: no se reintenta
    # sola, no cuenta como fallo del producto y no manda a mirar el portal.
    CANCELADA = "cancelada"

    # Las que todavia tienen algo que hacer. Es la cola de verdad, y lo que
    # cuenta el badge de la pantalla.
    VIVAS = (PENDIENTE, EN_CURSO)

    id = Column(Integer, primary_key=True)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    plataforma = Column(String(20), nullable=False)

    accion = Column(String(30), nullable=False)   # apagar_hoy | apagar_indef | prender
    estado = Column(String(20), default=PENDIENTE)
    intentos = Column(Integer, default=0)
    detalle = Column(Text, default="")

    # Un ERROR definitivo no se queda esperando a que el usuario se acuerde:
    # unos minutos despues la app lo reintenta sola (ver worker._reencolar_
    # fallidas). Estas dos columnas son las que evitan que eso sea un loop:
    #
    #   reintentada  -> esta fallida ya se miro una vez. Se marca SIEMPRE,
    #                   se haya reencolado o no, asi que ninguna se evalua
    #                   dos veces.
    #   auto_reintentos -> cuantos reintentos automaticos lleva la cadena.
    #                   La copia hereda el numero + 1 y hay un tope: si el
    #                   portal cambio un selector, reintentar cada 10 min
    #                   para siempre es machacarlo sin arreglar nada.
    #
    # Las bases viejas las reciben por ALTER TABLE (ver database.py), con
    # NULL en las filas que ya existian: se leen como 0 / False.
    reintentada = Column(Boolean, default=False)
    auto_reintentos = Column(Integer, default=0)

    # No tomar esta operacion antes de esta hora. NULL = ya mismo.
    #
    # Es lo que evita que una operacion que falla frene a las demas: la cola
    # se ordena por creada_en, asi que una fallida que vuelve a PENDIENTE
    # gana el turno otra vez a los 2 segundos y las 29 de atras esperan a la
    # que no entra (log del 2026-08-05). Con esto sigue teniendo sus 3
    # intentos, pero al final de la fila.
    reintentar_en = Column(DateTime, nullable=True)

    creada_en = Column(DateTime, default=datetime.now)
    finalizada_en = Column(DateTime, nullable=True)

    producto = relationship("Producto")
