"""PedidosYa Partner.

ESTRUCTURA DE LA PANTALLA (captura del usuario, 2026-07-27):
  Columna izquierda: navegacion del portal (Menues, Ajustes, ...).
  Columna del medio:  las categorias del menu, como las tenga tu carta.
  Columna derecha:    los productos de la categoria elegida, con su toggle.

  El portal carga UNA categoria por vez: por eso el DOM tiene solo los
  productos de la categoria abierta, no la carta entera. Ver CATEGORIAS.

  El puntito a la derecha de cada fila distingue el tipo de apagado:
  amarillo = "no disponible por hoy", gris = "indefinidamente". Todavia no
  se usa; leer_estado() solo devuelve si esta disponible o no.

FLUJO OBSERVADO (capturas del usuario):
  1. Lista de productos agrupados por categoria
  2. Cada producto tiene un toggle a la izquierda del nombre
  3. Al clickear el toggle de un producto PRENDIDO, se abre un popup con:
       - titulo = nombre del producto
       - "Unavailable for today"      (punto amarillo)
       - "Unavailable indefinitely"   (punto gris)
     OJO: el portal esta EN INGLES, aunque las capturas iniciales se
     hubieran leido en castellano. Ver TXT_POR_HOY.
  4. Al clickear el toggle de un producto APAGADO lo prende directo, sin
     popup. CONFIRMADO EN VIVO (op#17, 2026-07-27).

CONFIRMADO POR HTML (DevTools, 2026-07-27): los toggles son
<mat-slide-toggle> de Angular Material:

    <label class="mat-slide-toggle-label" for="mat-slide-toggle-22-input">
      <span class="mat-slide-toggle-bar">
        <input type="checkbox" role="switch"
               class="mat-slide-toggle-input cdk-visually-hidden"
               id="mat-slide-toggle-22-input" aria-checked="false">
        ...
      </span>
      <span class="mat-slide-toggle-content">
        <p class="... item-name">Nombre del producto</p>
      </span>
    </label>

El <label class="mat-slide-toggle-label"> envuelve tanto el nombre del
producto como el toggle: es la fila. El estado se lee 100% de
aria-checked ("true"/"false") sobre el <input>.

=========================================================================
 ESTADO: los cuatro metodos del contrato corrieron en vivo contra el
 portal. apagar() y prender() estan confirmados; el recorrido de
 categorias tambien (op#17 encontro el producto en otra categoria), con la
 salvedad de _abrir_categoria: cuando el click tiene que ir por el
 fallback JS hay que clickear adentro del custom element, no el custom
 element. Ver ahi.
=========================================================================
"""

import asyncio
import json
import logging
import re
from time import monotonic
from typing import Optional
from urllib.parse import urlsplit

from .base import (DuracionNoConfirmada, NombreAmbiguo, PlataformaBase,
                   ResultadoEstado, ResultadoTienda)

log = logging.getLogger("pedidosya")


class VerificacionHumanaPendiente(RuntimeError):
    """El portal requiere intervención humana; la operación queda pendiente."""


class ApagadoSinConfirmar(RuntimeError):
    """El portal pudo haber recibido el apagado antes de fallar la confirmación."""


class SwitchDeshabilitado(RuntimeError):
    """El portal impide activar el control de disponibilidad."""


class PedidosYa(PlataformaBase):
    nombre = "pedidosya"

    # El id del menu es el de TU sucursal: si te logueas en otra, la app
    # navega de vuelta a esta. Sale de Ajustes y no tiene default, porque
    # no hay ninguno razonable: el de otro local manda la app a un menu
    # ajeno, que es peor que no arrancar.
    MENU_ID = ""
    BASE_MENU = "https://web-ar.us.restaurant-partners.com/menus/PY_AR"

    @property
    def url_menu(self) -> str:
        return f"{self.BASE_MENU}/{self.menu_id}"

    @property
    def configurado(self) -> bool:
        return bool(self.menu_id)

    # --- Opciones del popup de disponibilidad ---
    # CONFIRMADO POR LOG (2026-07-27): el portal esta EN INGLES. El popup
    # dice "<producto> | Unavailable for today | Unavailable indefinitely".
    # Buscabamos el texto en castellano, no lo encontrabamos, y por eso
    # fallaba el apagado aunque el click estuviera entrando bien.
    # Se aceptan los dos idiomas por si el portal cambia de locale.
    TXT_POR_HOY = re.compile(r"^(no disponible por hoy|unavailable for today)$", re.I)
    TXT_INDEFINIDO = re.compile(
        r"^(no disponible indefinidamente|unavailable indefinitely)$", re.I)

    # Popup de "Let's make sure the application can play sounds" que sale
    # al reloguear (una vez por dia).
    RE_PLAY_SOUND = re.compile(r"^\s*play\s*sound\s*$", re.I)

    # CONFIRMADO POR /api/esqueleto (2026-07-27): las categorias del menu
    # son <wk-menu-list-category-item> adentro de <wk-menu-list>:
    #
    #   wk-menu-list
    #     div.menus-list-item
    #       wk-menu-list-category-item.menu-category   -> "<categoria 1>"
    #       wk-menu-list-category-item.menu-category   -> "<categoria 2>"
    #
    # Se toma por estructura y no por nombre a proposito: asi funciona en
    # cualquier local, con las categorias que sea y en el idioma que sea.
    #
    # El "wk-menu-list" del principio importa: afuera de ese contenedor hay
    # otros dos wk-menu-list-category-item que NO son categorias del menu,
    # #unavailable-category ("Total unavailable", con el contador de
    # apagados) y #toppings-category.
    SELECTOR_CATEGORIAS = "wk-menu-list wk-menu-list-category-item"

    # HTML confirmado por el usuario. El iframe interior puede estar oculto
    # mientras el contenedor sigue bloqueando la carta. No leer tokens.
    SELECTOR_VERIFICACION = (
        '.px-captcha-container, #px-captcha, iframe#px-captcha-modal, '
        'iframe[title="Human verification challenge"]'
    )

    async def en_verificacion(self) -> bool:
        """Solo observa: nunca pulsa ni modifica la verificación."""
        for marco in self.page.frames:
            indicadores = marco.locator(self.SELECTOR_VERIFICACION)
            for i in range(await indicadores.count()):
                if await indicadores.nth(i).is_visible():
                    return True
        return False

    async def verificacion_resuelta(self) -> bool:
        """Comprueba que volvió el menú, incluso detrás del aviso de sonido."""
        if await self.en_verificacion() or not self.en_el_menu():
            return False
        carta = await self._carta_visible(permitir_fondo=True)
        return self._menu_cargado(carta) and not await self.en_verificacion()

    async def _exigir_sin_verificacion(self):
        if await self.en_verificacion():
            raise VerificacionHumanaPendiente(
                "PedidosYa pide verificar que sos humano: mantené pulsado "
                "Press & Hold en su pestaña; la cola espera sin perder el progreso.")

    def en_el_menu(self) -> bool:
        if not self.configurado:
            return False
        actual = urlsplit(self.page.url)
        esperado = urlsplit(self.url_menu)
        return ((actual.scheme, actual.netloc, actual.path.rstrip("/"))
                == (esperado.scheme, esperado.netloc, esperado.path.rstrip("/")))

    async def _exigir_menu(self):
        await self._exigir_sin_verificacion()
        if not self.en_el_menu():
            raise RuntimeError("PedidosYa no está en el menú configurado en Ajustes.")

    async def ir_al_menu(self):
        await self._exigir_sin_verificacion()
        await super().ir_al_menu()
        await self._exigir_sin_verificacion()

    async def clickear(self, locator, timeout=8000, que="elemento", profundo=False):
        await self._exigir_menu()
        resultado = await super().clickear(locator, timeout, que, profundo)
        await self._exigir_menu()
        return resultado

    async def _diagnosticar(self, objetivo):
        # Si apareció durante el click normal, cortar antes de los fallbacks.
        await self._exigir_menu()
        return await super()._diagnosticar(objetivo)

    async def clickear_por_js(self, locator, profundo=False, timeout=8000):
        await self._exigir_menu()
        return await super().clickear_por_js(locator, profundo, timeout)

    async def recargar_y_preparar(self, por_que="", asentar=1500):
        await self._exigir_sin_verificacion()
        lista = await super().recargar_y_preparar(por_que, asentar)
        await self._exigir_sin_verificacion()
        return lista

    # Cada fila es el <label class="mat-slide-toggle-label"> de Angular
    # Material, que envuelve nombre + toggle. Su `for` apunta al <input> de
    # esa fila y nada mas, asi que identifica la fila sin ambiguedad.
    XPATH_TARJETA = ("xpath=ancestor::label"
                     "[contains(@class,'mat-slide-toggle-label')][1]")
    ATRIBUTO_ID_TARJETA = "for"

    def __init__(self, page, menu_id: str = None):
        super().__init__(page)
        self.menu_id = menu_id or self.MENU_ID
        self._categorias_leidas = {}

    def configurar(self, menu_id: str):
        """Cambia de menú y descarta las categorías de la sucursal anterior."""
        if menu_id != self.menu_id:
            self.menu_id = menu_id
            self._categorias_leidas = {}

    def _boton_sonido(self):
        return self.page.locator("button:visible").filter(has_text=self.RE_PLAY_SOUND)

    async def _cerrar_popups(self) -> bool:
        """Cierra el aviso de sonido o un diálogo residual de disponibilidad."""
        await self._exigir_menu()
        boton = self._boton_sonido()
        if await boton.count() == 1:
            try:
                await boton.click(timeout=1800)
                await self._exigir_menu()
                return True
            except VerificacionHumanaPendiente:
                raise
            except Exception as e:
                await self._exigir_menu()
                # El botón puede conservar el foco aunque un aviso tape su centro.
                if await boton.count() == 1 and await boton.is_enabled():
                    enfocado = await boton.evaluate("el => el === document.activeElement")
                    if enfocado:
                        await self._exigir_menu()
                        try:
                            await boton.and_(self.page.locator(":focus")).press("Enter", timeout=1800)
                        except Exception:
                            await self._exigir_menu()
                        else:
                            await self._exigir_menu()
                            return True
                log.warning("PedidosYa: el botón de sonido todavía no responde: %s",
                            self._motivo_del_click(e))
                return False

        if await self._hay_overlay():
            dialogo = self.page.locator(self.SELECTOR_POPUP).filter(
                has=self.page.get_by_text(self.TXT_POR_HOY)).filter(
                has=self.page.get_by_text(self.TXT_INDEFINIDO))
            if await dialogo.count() == 1:
                await self._exigir_menu()
                await self.page.keyboard.press("Escape")
                return True
        return False

    async def _hay_overlay(self) -> bool:
        return (await self.page.locator(".cdk-overlay-backdrop:visible").count() > 0
                or await self._boton_sonido().count() > 0)

    @staticmethod
    def _menu_cargado(carta: dict) -> bool:
        categorias = carta["categorias"]
        return (bool(categorias) and all(categorias)
                and len(set(categorias)) == len(categorias)
                and any(fila["nombre"] for fila in carta["filas"]))

    async def asegurar_sesion(self) -> bool:
        if await self.en_verificacion():
            return False
        await self.ir_al_menu()
        if not self.en_el_menu():
            return False

        fin = monotonic() + self.ESPERA_MENU
        anterior = None
        aviso_pendiente = False
        while monotonic() < fin:
            await self._exigir_menu()
            if await self.page.locator('input[type="password"]:visible').count():
                return False

            carta = await self._carta_visible()
            aviso_pendiente = await self._hay_overlay()
            if aviso_pendiente:
                anterior = None
                await self._cerrar_popups()
            elif self._menu_cargado(carta):
                if anterior == carta["categorias"]:
                    await self._exigir_menu()
                    return True
                anterior = carta["categorias"]
            else:
                anterior = None
            await asyncio.sleep(self.ESTABILIZACION)

        log.warning("PedidosYa: menú sin confirmar (categorías=%d, filas=%d, diálogo=%s)",
                    len(carta["categorias"]), len(carta["filas"]), aviso_pendiente)
        return False

    SELECTOR_FILAS = "label.mat-slide-toggle-label"
    SELECTOR_NOMBRE = ".item-name"
    SELECTOR_POPUP = ".cdk-overlay-pane:visible"
    ESPERA_MENU = 15
    ESPERA_CATEGORIA = 7
    ESTABILIZACION = 0.45

    # Leer de una vez evita combinar el nombre de una fila con el switch
    # de otra mientras Angular reemplaza los productos.
    JS_CARTA_VISIBLE = r"""
        ({categorias, filas, nombre, permitirFondo}) => {
            const visible = el => el.getClientRects().length &&
                getComputedStyle(el).visibility === 'visible' &&
                (permitirFondo || !el.closest('[aria-hidden="true"], [inert]'));
            const texto = el => el.innerText.trim().replace(/\s+/g, ' ');
            const seleccionada = '[aria-current="true"], [aria-selected="true"]';
            const items = [...document.querySelectorAll(categorias)].filter(visible);
            const activas = items.filter(el => el.matches(seleccionada) ||
                [...el.querySelectorAll(seleccionada)].some(visible));
            return {
                categorias: items.map(texto),
                activa: activas.length === 1 ? texto(activas[0]) : null,
                filas: [...document.querySelectorAll(filas)].filter(visible).map(fila => {
                    const titulos = [...fila.querySelectorAll(nombre)].filter(visible);
                    const controles = fila.querySelectorAll('input[type="checkbox"]');
                    const toggle = controles.length === 1 ? controles[0] : null;
                    const id = fila.htmlFor;
                    const aria = toggle?.getAttribute('aria-checked');
                    const valido = id && toggle && fila.control === toggle &&
                        toggle.id === id &&
                        document.querySelectorAll('#' + CSS.escape(id)).length === 1;
                    let disponible = null;
                    if (valido) {
                        if (aria === null) disponible = toggle.checked;
                        if (aria === 'true' && toggle.checked) disponible = true;
                        if (aria === 'false' && !toggle.checked) disponible = false;
                    }
                    return {nombre: titulos.length === 1 ? texto(titulos[0]) : '',
                            id, disponible};
                }),
            };
        }
    """

    async def _carta_visible(self, *, permitir_fondo=False) -> dict:
        await self._exigir_menu()
        return await self.page.evaluate(self.JS_CARTA_VISIBLE, {
            "categorias": self.SELECTOR_CATEGORIAS,
            "filas": self.SELECTOR_FILAS,
            "nombre": self.SELECTOR_NOMBRE,
            "permitirFondo": permitir_fondo,
        })

    async def categorias(self) -> list[str]:
        return (await self._carta_visible())["categorias"]

    async def categorias_de_productos(self) -> dict:
        """Devuelve las categorías de los nombres únicos de la última carta."""
        salida = {}
        repetidos = set()
        for categoria, nombres in self._categorias_leidas.items():
            for nombre in nombres:
                if nombre in salida:
                    repetidos.add(nombre)
                salida[nombre] = categoria
        return {nombre: categoria for nombre, categoria in salida.items()
                if nombre not in repetidos}

    @staticmethod
    def _huella(filas):
        return [(fila["id"], fila["nombre"]) for fila in filas]

    async def _abrir_categoria(self, categoria, categorias, *, aceptar_cache=True):
        """Espera filas de la categoría solicitada o devuelve None."""
        antes = await self._carta_visible()
        if antes["categorias"] != categorias:
            raise RuntimeError("Cambió la lista de categorías de PedidosYa durante la lectura.")
        huella_anterior = self._huella(antes["filas"])
        nombres_antes = sorted(fila["nombre"] for fila in antes["filas"])
        conocida = (aceptar_cache
                    and self._categorias_leidas.get(categoria) == nombres_antes
                    and list(self._categorias_leidas.values()).count(nombres_antes) == 1)
        ya_abierta = (len(categorias) == 1 or antes["activa"] == categoria
                      or (antes["activa"] is None and conocida))
        if not ya_abierta:
            selector = self.page.locator(f"{self.SELECTOR_CATEGORIAS}:visible")
            texto = r"^\s*" + r"\s+".join(map(re.escape, categoria.split())) + r"\s*$"
            destino = selector.filter(has_text=re.compile(texto))
            if await destino.count() != 1:
                return None
            await self.clickear(destino, timeout=2500, que=f"categoría {categoria}",
                                profundo=True)

        anterior = None
        fin = monotonic() + self.ESPERA_CATEGORIA
        while monotonic() < fin:
            actual = await self._carta_visible()
            if actual["categorias"] != categorias:
                raise RuntimeError("Cambió la lista de categorías de PedidosYa durante la lectura.")
            filas = actual["filas"]
            activa = actual["activa"]
            if (filas and all(fila["nombre"] for fila in filas)
                    and (activa is None or activa == categoria)
                    and (ya_abierta or self._huella(filas) != huella_anterior)):
                if filas == anterior:
                    return filas
                anterior = filas
            else:
                anterior = None
            await asyncio.sleep(self.ESTABILIZACION)
        return None

    async def _leer_carta(self):
        await self.ir_al_menu()
        inicial = await self._carta_visible()
        if not self._menu_cargado(inicial) and await self.asegurar_sesion():
            inicial = await self._carta_visible()
        categorias = inicial["categorias"]
        if not self._menu_cargado(inicial):
            self._categorias_leidas = {}
            raise RuntimeError("PedidosYa: no se pudo identificar la lista de categorías.")

        # Empezar por otra categoría permite comprobar el cambio de filas
        # aunque el portal no anuncie qué categoría tiene seleccionada.
        iniciales = sorted(fila["nombre"] for fila in inicial["filas"])
        anterior = inicial["activa"] or next(
            (cat for cat, nombres in self._categorias_leidas.items() if nombres == iniciales),
            categorias[0],
        )
        orden = [categoria for categoria in categorias if categoria != anterior]
        if anterior in categorias:
            orden.append(anterior)
        leidas = {}
        try:
            for categoria in orden:
                filas = await self._abrir_categoria(categoria, categorias, aceptar_cache=False)
                if filas is None:
                    raise RuntimeError(
                        f"PedidosYa: no se pudo confirmar la categoría «{categoria}».")
                leidas[categoria] = filas
            await self._exigir_menu()
        except Exception:
            self._categorias_leidas = {}
            raise

        self._categorias_leidas = {
            categoria: sorted(fila["nombre"] for fila in leidas[categoria])
            for categoria in categorias
        }
        return {categoria: leidas[categoria] for categoria in categorias}

    async def listar_productos(self) -> list[str]:
        carta = await self._leer_carta()
        return list(dict.fromkeys(fila["nombre"] for filas in carta.values()
                                  for fila in filas))

    async def leer_todos(self) -> dict:
        carta = await self._leer_carta()
        categorias = await self.categorias_de_productos()
        estados = {fila["nombre"]: fila["disponible"] for filas in carta.values()
                   for fila in filas
                   if fila["disponible"] is not None and fila["nombre"] in categorias}
        if not estados:
            raise RuntimeError("PedidosYa: no se pudo confirmar el estado de ningún producto.")
        return estados

    def _fila(self, nombre_remoto):
        nombre = self.page.locator(self.SELECTOR_NOMBRE).and_(
            self.page.get_by_text(nombre_remoto, exact=True))
        return self.page.locator(f"{self.SELECTOR_FILAS}:visible").filter(has=nombre)

    async def _buscar_producto(self, nombre_remoto, *, verificar_carta=False):
        self.ultimo_error_producto = ""
        await self.ir_al_menu()
        categorias = await self.categorias()
        releida = (verificar_carta or not categorias
                   or categorias != list(self._categorias_leidas))
        if releida:
            await self._leer_carta()
            categorias = list(self._categorias_leidas)

        while True:
            coincidencias = [categoria for categoria, nombres in self._categorias_leidas.items()
                             for nombre in nombres if nombre == nombre_remoto]
            if len(coincidencias) > 1:
                raise NombreAmbiguo(
                    f"«{nombre_remoto}» aparece más de una vez en PedidosYa "
                    f"({', '.join(dict.fromkeys(coincidencias))}).")
            if coincidencias:
                filas = await self._abrir_categoria(coincidencias[0], categorias)
                if filas is not None:
                    encontradas = [fila for fila in filas if fila["nombre"] == nombre_remoto]
                    if len(encontradas) > 1:
                        raise NombreAmbiguo(f"«{nombre_remoto}» tiene varias filas en PedidosYa.")
                    if encontradas:
                        fila = encontradas[0]
                        if fila["disponible"] is None:
                            self.ultimo_error_producto = (
                                f"No se pudo leer el switch de «{nombre_remoto}» en PedidosYa.")
                        return fila
            if releida:
                self.ultimo_error_producto = f"No se pudo confirmar «{nombre_remoto}» en PedidosYa."
                return None
            await self._leer_carta()
            categorias = list(self._categorias_leidas)
            releida = True

    @staticmethod
    async def _motivo_switch_deshabilitado(control):
        return await control.evaluate("""el => {
            const bloqueo = el.closest('[disabled], [aria-disabled="true"], [inert]');
            if (!bloqueo) return el.matches(':disabled')
                ? 'disabled heredado' : 'el navegador lo informa deshabilitado';
            const atributos = ['disabled', 'aria-disabled', 'inert']
                .filter(nombre => bloqueo.hasAttribute(nombre));
            return bloqueo.localName + ' (' + atributos.join(', ') + ')';
        }""", timeout=1500)

    async def inspeccionar(self, nombre_remoto: str) -> dict:
        await self.ir_al_menu()
        fila = self._fila(nombre_remoto)
        datos = await self._html_de(fila.first)
        datos["popup_abierto"] = await self._hay_overlay()
        if await fila.count() == 1:
            control = fila.locator('input[type="checkbox"]')
            if await control.count() == 1:
                datos["switch_habilitado"] = await control.is_enabled(timeout=1500)
                if not datos["switch_habilitado"]:
                    datos["bloqueo"] = await self._motivo_switch_deshabilitado(control)
        return datos

    async def leer_estado(self, nombre_remoto: str) -> Optional[ResultadoEstado]:
        fila = await self._buscar_producto(nombre_remoto)
        if fila is None or fila["disponible"] is None:
            return None
        return ResultadoEstado(disponible=fila["disponible"], detalle="switch de PedidosYa")

    async def _control_producto(self, nombre_remoto, esperado):
        actual = await self._carta_visible()
        coincidencias = [fila for fila in actual["filas"] if fila["nombre"] == nombre_remoto]
        if coincidencias != [esperado]:
            raise RuntimeError(f"Cambió la fila de «{nombre_remoto}» antes de tocar el switch.")

        fila = self._fila(nombre_remoto)
        ident = json.dumps(esperado["id"], ensure_ascii=False)
        marcado = ":checked" if esperado["disponible"] else ":not(:checked)"
        aria = str(esperado["disponible"]).lower()
        selector = (f'input[type="checkbox"][id={ident}]{marcado}'
                    f':is([aria-checked="{aria}"], :not([aria-checked]))')
        fila = fila.and_(self.page.locator(f'label[for={ident}]:has({selector})'))
        control = fila.locator(selector)
        if await fila.count() != 1 or await control.count() != 1:
            raise RuntimeError(f"No se pudo identificar el switch de «{nombre_remoto}».")
        return fila, control

    async def _click_toggle(self, nombre_remoto, esperado):
        fila, _ = await self._control_producto(nombre_remoto, esperado)
        barra = fila.locator("span.mat-slide-toggle-bar:visible")
        if await barra.count() != 1:
            raise RuntimeError(f"No se pudo identificar la barra de «{nombre_remoto}».")
        await self.clickear(barra, timeout=3500, que=f"switch de {nombre_remoto}")

    async def _activar_checkbox(self, nombre_remoto, esperado):
        _, control = await self._control_producto(nombre_remoto, esperado)
        if await self._hay_overlay():
            raise RuntimeError("Hay un diálogo abierto sobre el menú de PedidosYa.")
        if not await control.is_enabled(timeout=2000):
            motivo = await self._motivo_switch_deshabilitado(control)
            raise SwitchDeshabilitado(
                f"PedidosYa tiene deshabilitado el switch de «{nombre_remoto}»: {motivo}.")
        await control.focus(timeout=2000)
        await self._exigir_menu()
        enfocado = control.and_(self.page.locator(":focus"))
        if await enfocado.count() != 1 or await self._hay_overlay():
            raise RuntimeError(f"No se pudo enfocar el switch de «{nombre_remoto}».")
        await enfocado.press("Space", timeout=2000)
        await self._exigir_menu()

    async def _confirmar(self, nombre_remoto, esperado_disponible, asentar=1500):
        lista = await self.recargar_y_preparar(
            por_que=f"reconfirmar «{nombre_remoto}»", asentar=asentar)
        if not lista:
            self.ultimo_error_producto = (
                "El menú de PedidosYa no quedó listo después de recargar para confirmar el cambio.")
            return False
        estado = await self.leer_estado(nombre_remoto)
        if estado is None:
            return False
        if estado.disponible != esperado_disponible:
            disponible = "disponible" if estado.disponible else "apagado"
            self.ultimo_error_producto = (
                f"Después de recargar, «{nombre_remoto}» sigue {disponible} en PedidosYa.")
            return False
        return True

    async def apagar(self, nombre_remoto: str, por_hoy: bool = True) -> bool:
        fila = await self._buscar_producto(nombre_remoto, verificar_carta=True)
        if fila is None or fila["disponible"] is None:
            return False
        if not fila["disponible"]:
            if not por_hoy:
                raise DuracionNoConfirmada(
                    "El producto ya está apagado y el portal no mostró la duración. "
                    "Podés cambiarla desde PedidosYa.")
            return True

        await self._click_toggle(nombre_remoto, fila)
        opcion = self.TXT_POR_HOY if por_hoy else self.TXT_INDEFINIDO
        popup = self.page.locator(self.SELECTOR_POPUP).filter(
            has=self.page.get_by_text(nombre_remoto, exact=True))
        try:
            await popup.wait_for(state="visible", timeout=5000)
            destino = popup.get_by_text(opcion)
            if await destino.count() != 1:
                raise RuntimeError("No se pudo identificar la opción de disponibilidad.")
            await self._exigir_menu()
        except VerificacionHumanaPendiente:
            raise
        except Exception as e:
            await self._exigir_menu()
            log.warning("No se confirmó el diálogo de «%s»: %s", nombre_remoto,
                        " ".join(str(e).split())[:150])
            await self.page.keyboard.press("Escape")
            return False

        detalle = (f"No se pudo confirmar el apagado de «{nombre_remoto}». "
                   "Revisá su disponibilidad en PedidosYa antes de volver a pedirlo.")
        try:
            log.info("PedidosYa: se envía el apagado solicitado de «%s» (%s)",
                     nombre_remoto, "por hoy" if por_hoy else "indefinido")
            await self.clickear(destino, que=f"duración de {nombre_remoto}")
            await popup.wait_for(state="hidden", timeout=5000)
            await self.page.wait_for_timeout(1500)
            if await self._confirmar(nombre_remoto, esperado_disponible=False):
                return True
        except Exception as e:
            raise ApagadoSinConfirmar(detalle) from e
        raise ApagadoSinConfirmar(detalle)

    async def prender(self, nombre_remoto: str) -> bool:
        fila = await self._buscar_producto(nombre_remoto, verificar_carta=True)
        if fila is None or fila["disponible"] is None:
            return False
        if fila["disponible"]:
            return True

        await self._activar_checkbox(nombre_remoto, fila)
        await self.page.wait_for_timeout(2000)
        return await self._confirmar(nombre_remoto, esperado_disponible=True)

    # CONFIRMADO POR /api/esqueleto (2026-07-30): en la barra superior de la
    # pantalla del menu (la misma que ya usamos para los productos, no hace
    # falta navegar a otro lado) hay:
    #
    #   wk-availability-status-button#tutorial-vendor-availability-status-button
    #     ... span "open"
    #     wk-availability-circle-icon.OPEN
    #
    # "closed" y la clase que le corresponde al icono NO estan confirmados
    # en vivo todavia (no vimos la tienda cerrada), pero son el complemento
    # obvio de "open"/OPEN. Si el texto o la clase no matchean ninguno de
    # los dos, se devuelve None: mejor "no se" que un color inventado.
    SELECTOR_ESTADO_TIENDA = "wk-availability-status-button"

    async def leer_estado_tienda(self) -> Optional[ResultadoTienda]:
        await self.ir_al_menu()

        boton = self.page.locator(self.SELECTOR_ESTADO_TIENDA)
        if await boton.count() == 0:
            return None

        texto = ""
        try:
            texto = (await boton.first.inner_text()).strip()
        except Exception:
            pass

        clases = ""
        icono = boton.locator("wk-availability-circle-icon").first
        if await icono.count() > 0:
            clases = (await icono.get_attribute("class")) or ""

        texto_l = texto.strip().lower()
        tokens_clase = clases.split()
        if texto_l == "open" or "OPEN" in tokens_clase:
            return ResultadoTienda(abierta=True, detalle=texto or clases)
        if texto_l == "closed" or "CLOSED" in tokens_clase:
            return ResultadoTienda(abierta=False, detalle=texto or clases)
        return None
