"""Prueba el modo "verificacion en dos pasos". Sin navegador ni portales.

    py pruebas/probar_verificacion.py

EL PROBLEMA (pedido del 2026-08-06). Rappi pide cada ~30 dias, ademas del
login, un codigo de verificacion que llega al mail del dueño de la cuenta.
Hay que quedarse en esa pantalla varios minutos esperandolo, y CUALQUIER
recarga o navegacion en el medio lo invalida: hay que empezar de nuevo.

El worker navega esa pestaña solo en trece lugares (todos pasan por
_preparar), asi que hacer la verificacion era una carrera contra la app.

Lo que se prueba aca es lo que tiene que ser cierto para que eso no pase:

  1. Con el modo prendido, _preparar corta ANTES de recargar y ANTES de
     asegurar_sesion() — que navega igual aunque no haya recarga.
  2. La cola de esa plataforma espera: no gasta intentos ni termina en ERROR.
  3. La otra plataforma sigue trabajando normal.
  4. Solo se sale con la accion explicita del usuario. NUNCA por tiempo.
  5. Congelar Rappi Turbo congela tambien Rappi Común (mismo login).
  6. La activacion MANUAL funciona sin depender de ningun selector.
"""

import asyncio
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

TEMPORAL = tempfile.mkdtemp(prefix="todoselector-verif-")
os.environ["HOME"] = TEMPORAL
os.environ["LOCALAPPDATA"] = TEMPORAL

from app import config                                       # noqa: E402
import catalogo_ejemplo                                      # noqa: E402
from app.database import SessionLocal, init_db               # noqa: E402
from app.models import Producto, Operacion, Preferencia      # noqa: E402
from app.worker import Worker                                # noqa: E402
from plataformas.rappi import Rappi                          # noqa: E402

catalogo_ejemplo.usar_catalogo()

fallos = []


def revisar(condicion, titulo):
    print(("  OK    " if condicion else "  FALLA ") + titulo)
    if not condicion:
        fallos.append(titulo)


# --------------------------------------------------------------- Dobles


class PaginaFalsa:
    """Una pestaña que ANOTA todo lo que le hacen.

    El punto de la prueba no es que algo devuelva False: es que NADIE toque
    la pestaña. Por eso lo que se mira es este registro y no el resultado.
    """

    def __init__(self, url="https://partners.rappi.com/login", cuerpo=""):
        self.url = url
        self.cuerpo = cuerpo
        self.tocada = []          # cada recarga / navegacion / cierre

    async def reload(self, **kw):
        self.tocada.append("reload")

    async def goto(self, url, **kw):
        self.tocada.append(f"goto {url}")
        self.url = url

    async def close(self):
        self.tocada.append("close")

    async def wait_for_timeout(self, ms):
        pass

    async def inner_text(self, selector):
        return self.cuerpo


class PlataformaFalsa:
    """Se comporta como una plataforma, y tambien anota."""

    def __init__(self, nombre, page=None, sesion=True, verificando=False):
        self.nombre = nombre
        self.page = page or PaginaFalsa()
        self.configurado = True
        self.url_menu = "https://portal/menu"
        self._sesion = sesion
        self._verificando = verificando
        self.sesiones_aseguradas = 0

    def en_el_menu(self):
        return self.url_menu in self.page.url

    def configurar(self, **kw):
        pass

    async def asegurar_sesion(self):
        # La de verdad arranca con ir_al_menu(): NAVEGA aunque la pestaña
        # este fresca. Es justo lo que hace que un corte puesto solo antes
        # del reload no alcance.
        self.sesiones_aseguradas += 1
        await self.page.goto(self.url_menu)
        return self._sesion

    async def en_verificacion(self):
        return self._verificando

    async def apagar(self, nombre_remoto, por_hoy=True):
        return True

    async def prender(self, nombre_remoto):
        return True

    async def leer_estado(self, nombre_remoto):
        return None

    async def leer_todos(self):
        return {}


def worker_con(plataformas, simulado=False):
    w = Worker()
    w.corriendo = True
    w.modo_simulado = simulado
    w.plataformas = dict(plataformas)
    return w


def limpiar_cola(db):
    db.query(Operacion).delete()
    db.commit()


def encolar(db, nombre, plataforma, accion="apagar_hoy"):
    p = db.query(Producto).filter_by(nombre=nombre).first()
    op = Operacion(producto_id=p.id, plataforma=plataforma, accion=accion)
    db.add(op)
    db.commit()
    return op.id


# ------------------------------------------------------------- Escenarios


def nadie_toca_la_pestana(db):
    """El corte de _preparar, que es el que cubre las trece puertas."""
    print("\n== Con el modo prendido, nadie toca la pestaña ==")

    pagina = PaginaFalsa()
    rappi = PlataformaFalsa("rappi", pagina)
    w = worker_con({"rappi": rappi})

    # Sin congelar: prepara normal (y se nota que TOCA la pestaña).
    listo, _ = asyncio.run(w._preparar("rappi"))
    revisar(listo, "sin congelar prepara normal")
    revisar(pagina.tocada, "y para eso navega la pestaña (linea de base)")

    w.congelar_por_verificacion("rappi")
    pagina.tocada.clear()
    rappi.sesiones_aseguradas = 0

    listo, motivo = asyncio.run(w._preparar("rappi"))
    revisar(not listo, "congelada, _preparar no deja pasar a nadie")
    revisar(pagina.tocada == [],
            f"y NO tocó la pestaña de ninguna forma (hizo: {pagina.tocada})")
    revisar(rappi.sesiones_aseguradas == 0,
            "ni siquiera llamó a asegurar_sesion(), que navega aunque no "
            "haya recarga")
    revisar("Ya termin" in motivo,
            "el motivo dice cómo salir, no solo que no se pudo")

    # El corte tiene que valer ESTE ademas del refresco previo: si dependiera
    # de la frescura de la pestaña, una recien refrescada pasaria igual.
    w.ultimo_refresco["rappi"] = datetime.now()
    pagina.tocada.clear()
    listo, _ = asyncio.run(w._preparar("rappi"))
    revisar(not listo and pagina.tocada == [],
            "tampoco pasa con la pestaña recién refrescada")


def la_otra_plataforma_sigue(db):
    print("\n== La otra plataforma sigue trabajando normal ==")

    pag_rappi, pag_py = PaginaFalsa(), PaginaFalsa()
    w = worker_con({"rappi": PlataformaFalsa("rappi", pag_rappi),
                    "pedidosya": PlataformaFalsa("pedidosya", pag_py)})
    w.congelar_por_verificacion("rappi")

    listo_py, _ = asyncio.run(w._preparar("pedidosya"))
    listo_rappi, _ = asyncio.run(w._preparar("rappi"))

    revisar(listo_py, "PedidosYa prepara igual que siempre")
    revisar(pag_py.tocada, "y sí toca su propia pestaña")
    revisar(not listo_rappi and pag_rappi.tocada == [],
            "mientras Rappi sigue intacta")


def las_dos_tiendas_de_rappi(db):
    """Congelar una congela a la hermana: entran con la MISMA cuenta."""
    print("\n== Congelar Rappi Turbo congela también Rappi Común ==")

    # Rappi Común solo existe si tiene storeId cargado (regla 9).
    db.add(Preferencia(clave="cfg_rappi_comun_store_id", valor="TIENDA2"))
    db.commit()
    config.recargar()

    w = worker_con({"rappi": PlataformaFalsa("rappi"),
                    "rappi_comun": PlataformaFalsa("rappi_comun"),
                    "pedidosya": PlataformaFalsa("pedidosya")})

    afectadas = w.congelar_por_verificacion("rappi")
    revisar(set(afectadas) == {"rappi", "rappi_comun"},
            f"congela las dos tiendas de Rappi (congeló: {afectadas})")
    revisar(w.en_verificacion("rappi_comun"),
            "Rappi Común queda congelada aunque no la nombraste")
    revisar(not w.en_verificacion("pedidosya"),
            "y PedidosYa no, que tiene su propio login")

    # Y al salir se sueltan las dos, no solo la que nombraste.
    asyncio.run(w.terminar_verificacion("rappi", leer=False))
    revisar(not w.verificacion, "«Ya terminé» suelta las dos de una")

    # Sin Rappi Común configurada, congelar Rappi es congelar Rappi y ya.
    db.query(Preferencia).filter_by(clave="cfg_rappi_comun_store_id").delete()
    db.commit()
    config.recargar()
    w2 = worker_con({"rappi": PlataformaFalsa("rappi")})
    revisar(w2.congelar_por_verificacion("rappi") == ["rappi"],
            "sin Rappi Común configurada no aparece de la nada")


def la_cola_espera_sin_gastarse(db):
    print("\n== La cola espera: no gasta intentos ni termina en ERROR ==")

    limpiar_cola(db)
    id_rappi = encolar(db, "Flan casero", "rappi")
    id_py = encolar(db, "Flan casero", "pedidosya")

    w = worker_con({"rappi": PlataformaFalsa("rappi"),
                    "pedidosya": PlataformaFalsa("pedidosya")})
    w.congelar_por_verificacion("rappi")

    # Dos vueltas de la cola: alcanzan para que la de Rappi se hubiera
    # gastado sus intentos si el corte no estuviera.
    asyncio.run(w._procesar_pendientes())
    asyncio.run(w._procesar_pendientes())
    db.expire_all()

    op_rappi = db.query(Operacion).get(id_rappi)
    op_py = db.query(Operacion).get(id_py)

    revisar(op_rappi.estado == Operacion.PENDIENTE,
            f"la de Rappi sigue pendiente (quedó en {op_rappi.estado})")
    revisar(op_rappi.intentos == 0,
            f"y no gastó ningún intento (gastó {op_rappi.intentos})")
    revisar(op_py.estado == Operacion.OK,
            f"la de PedidosYa salió igual (quedó en {op_py.estado})")

    # Y la espera NO VENCE. Es la diferencia con la sesion caida, que
    # reintenta a los 60 s: aca un plazo que vence solo le navegaria la
    # pestaña justo mientras espera el mail.
    revisar("rappi" not in w.reintentar_desde,
            "no se le pone hora de vuelta: esta espera no vence sola")

    w.reintentar_desde["rappi"] = datetime.now() - timedelta(hours=3)
    asyncio.run(w._procesar_pendientes())
    db.expire_all()
    revisar(db.query(Operacion).get(id_rappi).estado == Operacion.PENDIENTE,
            "ni pasando el tiempo: sigue esperando igual")

    # Recien cuando el usuario dice que termino, sale.
    asyncio.run(w.terminar_verificacion("rappi", leer=False))
    asyncio.run(w._procesar_pendientes())
    db.expire_all()
    revisar(db.query(Operacion).get(id_rappi).estado == Operacion.OK,
            "y apenas apretás «Ya terminé», sale sola")


def la_operacion_ya_tomada_no_se_gasta(db):
    """La carrera: la op se toma y RECIEN AHI aparece la verificacion."""
    print("\n== Si se congela con una operación ya tomada, tampoco se gasta ==")

    limpiar_cola(db)
    id_op = encolar(db, "Flan casero", "rappi")

    pagina = PaginaFalsa()
    rappi = PlataformaFalsa("rappi", pagina, sesion=False, verificando=True)
    w = worker_con({"rappi": rappi})

    # No esta congelada todavia: la cola la toma. Al preparar, asegurar_sesion
    # falla y la deteccion dice que es la pantalla del codigo.
    asyncio.run(w._procesar_pendientes())
    db.expire_all()
    op = db.query(Operacion).get(id_op)

    revisar(w.en_verificacion("rappi"),
            "la detección la congela sola cuando reconoce la pantalla")
    revisar(op.estado == Operacion.PENDIENTE,
            f"la operación vuelve a la cola (quedó en {op.estado})")
    revisar(op.intentos == 0,
            f"sin gastar el intento (gastó {op.intentos})")
    revisar("rappi" not in w.reintentar_desde,
            "y sin el reintento a los 60 s de la sesión caída, que le "
            "navegaría la pestaña")


def solo_sale_a_mano(db):
    print("\n== Solo se sale a mano, nunca por tiempo ni por un chequeo ==")

    pagina = PaginaFalsa()
    # verificando=False: aunque la pantalla YA no sea la del codigo, el modo
    # no se apaga solo. La app no puede mirar para saberlo sin navegar, que
    # es exactamente lo que no puede hacer.
    rappi = PlataformaFalsa("rappi", pagina, sesion=True, verificando=False)
    w = worker_con({"rappi": rappi})
    w.congelar_por_verificacion("rappi", origen="manual")

    # Congelada hace tres horas.
    w.verificacion["rappi"]["desde"] = datetime.now() - timedelta(hours=3)

    for _ in range(3):
        asyncio.run(w._preparar("rappi"))
    asyncio.run(w.revalidar_sesion("rappi"))
    asyncio.run(w._refrescar_estado_tiendas())

    revisar(w.en_verificacion("rappi"),
            "sigue congelada después de tres horas y de varios chequeos")
    revisar(pagina.tocada == [],
            f"y nadie tocó la pestaña (hizo: {pagina.tocada})")

    asyncio.run(w.terminar_verificacion("rappi", leer=False))
    revisar(not w.en_verificacion("rappi"), "el botón del usuario sí la saca")


def el_boton_manual_no_depende_de_selectores(db):
    """Lo que tiene que funcionar si o si, aunque la deteccion falle."""
    print("\n== El botón manual funciona aunque la detección falle ==")

    pagina = PaginaFalsa(cuerpo="una pantalla que no reconocemos")
    # verificando=False = la deteccion automatica NO la ve.
    rappi = PlataformaFalsa("rappi", pagina, sesion=False, verificando=False)
    w = worker_con({"rappi": rappi})

    revisar(not asyncio.run(rappi.en_verificacion()),
            "la detección automática no reconoce esta pantalla")

    w.empezar_verificacion("rappi")
    pagina.tocada.clear()
    listo, _ = asyncio.run(w._preparar("rappi"))

    revisar(not listo and pagina.tocada == [],
            "y aun así el botón la congela igual: no depende de ningún selector")
    revisar(w.verificacion["rappi"]["origen"] == "manual",
            "queda anotado que lo pediste vos")


def ajustes_no_le_cierran_la_pestana(db):
    """La unica puerta que no pasa por _preparar y no se puede recuperar."""
    print("\n== Guardar Ajustes no le cierra la pestaña a una congelada ==")

    db.add(Preferencia(clave="cfg_rappi_comun_store_id", valor="TIENDA2"))
    db.commit()
    config.recargar()

    pagina = PaginaFalsa()
    w = worker_con({"rappi": PlataformaFalsa("rappi"),
                    "rappi_comun": PlataformaFalsa("rappi_comun", pagina),
                    "pedidosya": PlataformaFalsa("pedidosya")})
    w.modo_simulado = True         # que aplicar_config no salga a leer nada
    w.congelar_por_verificacion("rappi")

    # Le borran el storeId a Rappi Común en el medio de la verificación.
    db.query(Preferencia).filter_by(clave="cfg_rappi_comun_store_id").delete()
    db.commit()
    config.recargar()

    asyncio.run(w.aplicar_config())
    revisar("close" not in pagina.tocada,
            f"no le cierra la pestaña (hizo: {pagina.tocada})")
    revisar("rappi_comun" in w.plataformas,
            "la deja abierta hasta que digas que terminaste")

    # Y al salir del modo, recién ahí se limpia.
    asyncio.run(w.terminar_verificacion("rappi", leer=False))
    revisar("rappi_comun" not in w.plataformas,
            "y al terminar sí se cierra: la limpieza no se pierde")


def lee_al_terminar(db):
    print("\n== Al terminar, lee por las dudas ==")

    w = worker_con({"rappi": PlataformaFalsa("rappi")})
    leidas = []

    async def sincronizar(plataforma=None, sostener=False):
        leidas.append(plataforma)
        return {}

    async def tiendas():
        leidas.append("tiendas")

    w.sincronizar_estados = sincronizar
    w._refrescar_estado_tiendas = tiendas
    w.congelar_por_verificacion("rappi")

    async def correr():
        salida = await w.terminar_verificacion("rappi", leer=True)
        # terminar_verificacion lanza la lectura en background para que el
        # boton conteste al toque: hay que dejarla correr.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return salida

    salida = asyncio.run(correr())

    revisar("rappi" in leidas, f"relee la plataforma que estuvo congelada "
                               f"(leyó: {leidas})")
    revisar("tiendas" in leidas, "y refresca el estado de tienda")
    revisar(salida["liberadas"] == ["rappi"] and salida["leyendo"],
            "y le avisa a la pantalla qué soltó")

    # La lectura NO puede ser condicion para salir del modo: si algo de la
    # lectura falla, la plataforma tiene que quedar libre igual.
    revisar(not w.verificacion, "el modo queda apagado pase lo que pase")


def la_pantalla_recibe_lo_que_necesita(db):
    print("\n== La pantalla recibe el estado, y no dos carteles opuestos ==")

    w = worker_con({"rappi": PlataformaFalsa("rappi")})
    w.sesion_ok = {"rappi": False, "pedidosya": True}
    w.congelar_por_verificacion("rappi", origen="manual", detalle="lo pediste vos")

    ui = w.verificacion_ui()
    revisar(isinstance(ui.get("rappi", {}).get("desde"), str),
            "la hora viaja como texto, que es lo que la API puede mandar")
    revisar(ui["rappi"]["origen"] == "manual", "y de dónde salió el modo")

    # sesion_ok sigue en False (el menu de verdad no cargo) y esta bien: lo
    # que no puede pasar es que la pantalla muestre los dos carteles juntos,
    # porque "logueate de nuevo" es lo contrario de "quedate quieto ahi".
    caidas = [p for p, ok in w.sesion_ok.items() if ok is False and p not in ui]
    revisar(caidas == [],
            "una plataforma congelada no sale además como sesión caída")


def deteccion_pide_dos_evidencias(db):
    """La deteccion de rappi.py, contra una pagina de mentira."""
    print("\n== La detección pide dos evidencias, no una ==")

    def con(url, cuerpo):
        plat = Rappi(PaginaFalsa(url, cuerpo), store_id="X", brand_id="Y")
        return asyncio.run(plat.en_verificacion())

    menu = "https://partners.rappi.com/menu?brandId=Y&storeIds=X&storeId=X"

    revisar(con("https://partners.rappi.com/login",
                "Probar otro método"),
            "reconoce la pantalla por el texto que ve el usuario")
    revisar(con("https://partners.rappi.com/login",
                "Ingresa el codigo que te enviamos"),
            "y lo compara sin tildes, como el resto del archivo")
    revisar(not con(menu, "Probar otro método"),
            "con el menú cargado NO la da por verificación, aunque el texto esté")
    revisar(not con("https://partners.rappi.com/login", "Ingresá tu contraseña"),
            "una sesión caída común sigue siendo una sesión caída")
    revisar(not con("https://partners.rappi.com/login", ""),
            "y una pantalla que no dice nada no se inventa nada (regla 8)")


def main():
    init_db()
    config.recargar()

    db = SessionLocal()
    try:
        from app.seed import sembrar
        sembrar()
        db.expire_all()

        nadie_toca_la_pestana(db)
        la_otra_plataforma_sigue(db)
        las_dos_tiendas_de_rappi(db)
        la_cola_espera_sin_gastarse(db)
        la_operacion_ya_tomada_no_se_gasta(db)
        solo_sale_a_mano(db)
        el_boton_manual_no_depende_de_selectores(db)
        ajustes_no_le_cierran_la_pestana(db)
        lee_al_terminar(db)
        la_pantalla_recibe_lo_que_necesita(db)
        deteccion_pide_dos_evidencias(db)
    finally:
        db.close()

    print()
    if fallos:
        print(f"{len(fallos)} FALLA(S):")
        for f in fallos:
            print("  - " + f)
    else:
        print("Todo OK.")
    shutil.rmtree(TEMPORAL, ignore_errors=True)
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
