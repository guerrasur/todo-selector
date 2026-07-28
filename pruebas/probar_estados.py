"""Prueba que la lectura del estado real se guarde bien. Sin navegador.

    py pruebas/probar_estados.py

Lo delicado no es leer el portal sino que se vuelca a la base: no pisar una
operacion en curso, no apropiarse de lo que apago el local por su cuenta, y
respetar el tipo de apagado que eligio el usuario.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

TEMPORAL = tempfile.mkdtemp(prefix="todoselector-estados-")
os.environ["HOME"] = TEMPORAL
os.environ["LOCALAPPDATA"] = TEMPORAL

from app import seed                                          # noqa: E402
from app.database import SessionLocal, init_db                # noqa: E402
from app.models import Producto, EstadoItem                   # noqa: E402
from app.worker import Worker                                 # noqa: E402

fallos = []


def revisar(condicion, titulo):
    print(("  OK    " if condicion else "  FALLA ") + titulo)
    if not condicion:
        fallos.append(titulo)


def estado_de(db, nombre, plataforma="rappi"):
    p = db.query(Producto).filter_by(nombre=nombre).first()
    if p is None:
        return None
    est = next((e for e in p.estados if e.plataforma == plataforma), None)
    return est.estado if est else None


def poner(db, nombre, valor, plataforma="rappi"):
    p = db.query(Producto).filter_by(nombre=nombre).first()
    est = next(e for e in p.estados if e.plataforma == plataforma)
    est.estado = valor
    db.commit()


def main():
    init_db()
    db = SessionLocal()
    try:
        seed.sembrar()
        db.expire_all()

        print("\n== La lectura llena lo que estaba en desconocido ==")
        revisar(estado_de(db, "Brie") == EstadoItem.DESCONOCIDO,
                "antes de leer, el producto esta en desconocido")

        # Como lo devuelve el portal: los nombres son los de Rappi.
        leido = {
            "Ensalada Brie": True,
            "Ensalada caesar": False,
            "Cobb": False,
            "Risotto de Hongos": True,
            "Ensalada cala": False,
        }

        # Estados de partida que la lectura tiene que respetar o pisar.
        poner(db, "Cobb", EstadoItem.APAGADO_HOY)          # lo apago la app
        poner(db, "Cala", EstadoItem.APAGANDO)             # operacion en vuelo
        poner(db, "Risotto", EstadoItem.APAGADO_HOY)       # la app lo apago...

        resultado = Worker._guardar_estados("rappi", leido)
        db.expire_all()

        revisar(estado_de(db, "Brie") == EstadoItem.PRENDIDO,
                "un producto disponible queda PRENDIDO")

        revisar(estado_de(db, "Caesar") == EstadoItem.APAGADO_AJENO,
                "uno apagado que la app no apago queda APAGADO_AJENO")

        revisar(estado_de(db, "Cobb") == EstadoItem.APAGADO_HOY,
                "uno que apago la app conserva 'apagado hoy'")

        revisar(estado_de(db, "Cala") == EstadoItem.APAGANDO,
                "una operacion en curso no la pisa la lectura")

        revisar(estado_de(db, "Risotto") == EstadoItem.PRENDIDO,
                "si el portal lo muestra prendido, gana el portal")

        revisar(resultado["prendidos"] == 2 and resultado["apagados"] == 2,
                f"cuenta bien lo leido: {resultado}")
        revisar(resultado["en_curso"] == 1, "cuenta la operacion en vuelo")
        revisar(resultado["no_estan"] > 0,
                "cuenta los del catalogo que el portal no mostro")

        print("\n== Lo que el portal no mostro no se pisa ==")
        antes = estado_de(db, "Brie")
        Worker._guardar_estados("rappi", {"Cobb": False})
        db.expire_all()
        revisar(estado_de(db, "Brie") == antes,
                "un producto ausente de la lectura conserva lo que sabiamos")

        print("\n== La reverificacion no se apropia de lo ajeno ==")
        # Es el motivo de que APAGADO_AJENO exista: _reverificar() solo
        # reencola lo que figura apagado por la app.
        apagados_que_sostiene = (db.query(EstadoItem)
                                 .filter(EstadoItem.estado.in_(
                                     EstadoItem.APAGADOS_PROPIOS))
                                 .all())
        nombres = {e.producto.nombre for e in apagados_que_sostiene}
        revisar("Caesar" not in nombres,
                "lo apagado desde el portal no entra en la ronda de reverificacion")
        revisar("Cobb" in nombres,
                "lo que apago la app si entra")
    finally:
        db.close()
        shutil.rmtree(TEMPORAL, ignore_errors=True)

    print("\n" + ("TODO OK" if not fallos else f"{len(fallos)} FALLAS: {fallos}"))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
