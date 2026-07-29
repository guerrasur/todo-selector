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

import logging
import re
from typing import Optional

from .base import PlataformaBase, ResultadoEstado

log = logging.getLogger("pedidosya")


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
    TXT_POR_HOY = re.compile(r"(no disponible por hoy|unavailable for today)", re.I)
    TXT_INDEFINIDO = re.compile(
        r"(no disponible indefinidamente|unavailable indefinitely)", re.I)

    # Popup de "Let's make sure the application can play sounds" que sale
    # al reloguear (una vez por dia).
    RE_PLAY_SOUND = re.compile(r"play\s*sound", re.I)

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

    def __init__(self, page, menu_id: str = None):
        super().__init__(page)
        self.menu_id = menu_id or self.MENU_ID
        # nombre_remoto -> indice de la categoria donde lo encontramos, para
        # no tener que recorrerlas todas cada vez.
        self._categoria_de = {}

    def configurar(self, menu_id: str):
        """Cambia de sucursal sin reiniciar la app. Olvida lo aprendido.

        El mapa de categorias es de ESTE menu: si cambia el local, las
        categorias son otras y buscar en la #2 de antes no significa nada.
        """
        if menu_id and menu_id != self.menu_id:
            log.info("PedidosYa pasa al menu %s (antes %s)", menu_id, self.menu_id)
            self.menu_id = menu_id
            self._categoria_de = {}

    async def _cerrar_popups(self) -> bool:
        """Cierra el popup de sonido que PedidosYa muestra al reloguear.

        Aparece una vez por dia. Mientras esta abierto tapa parte de la
        lista, y un click sobre lo que quede debajo falla con "intercepts
        pointer events" hasta el timeout.

        OJO: esto NO explica el "element is not enabled" que se vio el
        2026-07-27. Ese mensaje solo lo produce un `disabled`, un
        `aria-disabled="true"` o un <fieldset disabled> padre (verificado
        contra Playwright 1.61). Ver inspeccionar().
        """
        boton = self.page.get_by_role("button", name=self.RE_PLAY_SOUND)
        if await boton.count() > 0:
            try:
                await boton.first.click(timeout=5000)
                await self.page.wait_for_timeout(1000)
                log.info("Popup de sonido cerrado")
                return True
            except Exception as e:
                log.warning("No pude cerrar el popup de sonido: %s", e)

        # Puede haber quedado colgado el popup de disponibilidad de un
        # intento anterior. Si no se cierra, el proximo click cae sobre el
        # backdrop y el reintento nace muerto.
        if await self._hay_overlay():
            texto = await self.texto_overlay()
            log.warning("Cierro un dialogo que quedo abierto: %s", texto or "(sin texto)")
            await self.page.keyboard.press("Escape")
            await self.page.wait_for_timeout(800)
            return True

        return False

    async def _hay_overlay(self) -> bool:
        """Queda algun dialogo tapando el menu? Solo para avisar en el log."""
        try:
            return await self.page.locator(".cdk-overlay-backdrop").count() > 0
        except Exception:
            return False

    async def asegurar_sesion(self) -> bool:
        await self.ir_al_menu()

        # Antes que nada: si hay un popup abierto, tapa parte de la lista
        # y los clicks que caigan debajo van a fallar por timeout.
        await self._cerrar_popups()
        if await self._hay_overlay():
            log.warning("Hay un dialogo abierto en la pestaña de PedidosYa "
                        "que no supe cerrar: los clicks pueden fallar")

        # CONFIRMADO: PedidosYa no muestra pantalla de sesion expirada,
        # se re-loguea solo. Dejamos el chequeo de password como red de
        # seguridad por si en el futuro llegara a pedir login manual.
        if await self.page.locator('input[type="password"]').count() > 0:
            return False

        # CONFIRMADO: el menu usa toggles Angular Material
        # (mat-slide-toggle-input). Esperar a que aparezca al menos uno
        # es mejor evidencia de que el menu cargo que buscar una
        # categoria por nombre (puede no estar si no hay stock ese dia).
        try:
            await self.page.wait_for_selector(
                "input.mat-slide-toggle-input", timeout=15000
            )
            return True
        except Exception:
            return False

    async def _click_toggle(self, fila):
        """Clickea el toggle de la fila.

        OJO: el <input> tiene la clase cdk-visually-hidden de Angular
        Material y clickearlo directo NO funciona. Verificado contra una
        pagina de prueba con este mismo HTML: el click al input tarda
        30.0s exactos y falla. Hay que clickear la barra visible.
        """
        barra = fila.locator("span.mat-slide-toggle-bar").first
        # El <label> entero tambien togglea (semantica de label).
        objetivo = barra if await barra.count() > 0 else fila
        await self.clickear(objetivo, timeout=10000, que="toggle")

    async def _nombres_visibles(self) -> list[str]:
        """Los productos que la pagina tiene renderizados ahora mismo."""
        filas = self.page.locator("label.mat-slide-toggle-label")
        nombres = []
        for i in range(await filas.count()):
            try:
                texto = " ".join((await filas.nth(i).inner_text()).split())
            except Exception:
                continue
            if texto:
                nombres.append(texto)
        return nombres

    async def categorias(self) -> list[str]:
        """Los nombres de las categorias del menu, en orden."""
        cats = self.page.locator(self.SELECTOR_CATEGORIAS)
        nombres = []
        for i in range(await cats.count()):
            try:
                nombres.append(" ".join((await cats.nth(i).inner_text()).split()))
            except Exception:
                nombres.append("?")
        return nombres

    async def _abrir_categoria(self, indice: int) -> bool:
        """Clickea la categoria numero `indice`. True si cambio la lista."""
        cats = self.page.locator(self.SELECTOR_CATEGORIAS)
        if indice >= await cats.count():
            return False

        antes = await self._nombres_visibles()
        try:
            entro = await self.clickear(cats.nth(indice), timeout=5000,
                                        que=f"categoria #{indice}")
        except Exception as e:
            log.warning("No pude abrir la categoria #%s: %s",
                        indice, " ".join(str(e).split())[:100])
            return False

        await self.page.wait_for_timeout(1500)
        if await self._nombres_visibles() != antes:
            return True

        # El click normal entro y la lista no cambio: la categoria ya estaba
        # abierta. Es lo que pasa con la primera en cada recorrido.
        if entro:
            return False

        # Fue por el fallback JS y no paso nada. CONFIRMADO POR LOG
        # (2026-07-27): asi fallaron las 3 categorias al reconfirmar op#17.
        # El handler no esta en <wk-menu-list-category-item> sino adentro,
        # y un click disparado sobre el custom element no le llega.
        log.info("La categoria #%s no reacciono al click por JS; "
                 "reintento sobre el hijo que ocupa el centro", indice)
        try:
            tag = await self.clickear_por_js(cats.nth(indice), profundo=True,
                                             timeout=5000)
        except Exception as e:
            log.warning("Tampoco pude abrir la categoria #%s: %s",
                        indice, " ".join(str(e).split())[:100])
            return False

        await self.page.wait_for_timeout(1500)
        cambio = await self._nombres_visibles() != antes
        log.info("Categoria #%s por JS sobre <%s>: %s", indice, tag,
                 "cambio la lista" if cambio else "sigue sin cambiar")
        return cambio

    async def _mostrar_producto(self, nombre_remoto: str) -> bool:
        """Deja el producto en el DOM, cambiando de categoria si hace falta."""
        if await self._fila(nombre_remoto).count() > 0:
            return True

        total = await self.page.locator(self.SELECTOR_CATEGORIAS).count()
        if total == 0:
            log.warning("No encuentro la lista de categorias (%s)",
                        self.SELECTOR_CATEGORIAS)
            return False

        # Empezamos por donde lo encontramos la vez pasada.
        recordado = self._categoria_de.get(nombre_remoto)
        orden = ([recordado] if recordado is not None else [])
        orden += [i for i in range(total) if i != recordado]

        for indice in orden:
            await self._abrir_categoria(indice)
            if await self._fila(nombre_remoto).count() > 0:
                if self._categoria_de.get(nombre_remoto) != indice:
                    log.info("'%s' esta en la categoria '%s'", nombre_remoto,
                             (await self.categorias())[indice])
                self._categoria_de[nombre_remoto] = indice
                return True

        log.warning("'%s' no aparece en ninguna de las %s categorias",
                    nombre_remoto, total)
        return False

    def _fila(self, nombre_remoto: str):
        """Devuelve el locator de la fila del producto.

        CONFIRMADO: cada fila es el <label class="mat-slide-toggle-label">
        de Angular Material, que envuelve nombre + toggle. Buscamos el
        texto exacto (exact=True, cuidado con nombres que son prefijo de
        otros: 'Tarta de verdura' vs 'Tarta de verdura chica') y subimos al
        label ancestro.
        """
        texto = self.page.get_by_text(nombre_remoto, exact=True).first
        return texto.locator(
            "xpath=ancestor::label[contains(@class,'mat-slide-toggle-label')][1]"
        )

    async def listar_productos(self) -> list[str]:
        """Recorre todas las categorias: la carta entera, no solo la abierta."""
        await self.ir_al_menu()
        total = await self.page.locator(self.SELECTOR_CATEGORIAS).count()

        nombres = []
        for indice in range(total):
            await self._abrir_categoria(indice)
            for nombre in await self._nombres_visibles():
                if nombre not in nombres:
                    nombres.append(nombre)
        return nombres

    async def leer_todos(self) -> dict:
        """{nombre: disponible} de toda la carta, recorriendo las categorias.

        Producto por producto seria una busqueda por nombre y un cambio de
        categoria por cada uno. Aca cada categoria se abre UNA vez y se leen
        de corrido las filas que tiene a la vista, que es de donde salen el
        nombre y el aria-checked juntos.

        De paso deja aprendido en que categoria vive cada producto, asi la
        primera operacion del dia no tiene que salir a buscarlo.
        """
        await self.ir_al_menu()
        total = await self.page.locator(self.SELECTOR_CATEGORIAS).count()
        if total == 0:
            log.warning("No encuentro la lista de categorias (%s)",
                        self.SELECTOR_CATEGORIAS)
            return {}

        salida = {}
        for indice in range(total):
            await self._abrir_categoria(indice)

            filas = self.page.locator("label.mat-slide-toggle-label")
            for i in range(await filas.count()):
                fila = filas.nth(i)
                try:
                    nombre = " ".join((await fila.inner_text()).split())
                except Exception:
                    continue
                if not nombre or nombre in salida:
                    continue

                toggle = fila.locator(
                    'input[type="checkbox"], [role="switch"], button[aria-checked]'
                ).first
                if await toggle.count() == 0:
                    continue
                aria = await toggle.get_attribute("aria-checked")
                if aria is None:
                    try:
                        salida[nombre] = await toggle.is_checked()
                    except Exception:
                        continue
                else:
                    salida[nombre] = (aria == "true")

                self._categoria_de[nombre] = indice

        return salida

    async def inspeccionar(self, nombre_remoto: str) -> dict:
        await self.ir_al_menu()
        datos = await self._html_de(self._fila(nombre_remoto))
        datos["popup_abierto"] = await self._hay_overlay()
        return datos

    async def leer_estado(self, nombre_remoto: str) -> Optional[ResultadoEstado]:
        await self.ir_al_menu()
        if not await self._mostrar_producto(nombre_remoto):
            return None

        fila = self._fila(nombre_remoto)

        # CONFIRMADO: el toggle es <input type="checkbox" role="switch"
        # aria-checked="true|false">. aria-checked es la fuente de verdad.
        toggle = fila.locator(
            'input[type="checkbox"], [role="switch"], button[aria-checked]'
        ).first

        if await toggle.count() == 0:
            return ResultadoEstado(disponible=False, detalle="toggle no encontrado")

        aria = await toggle.get_attribute("aria-checked")
        if aria is not None:
            return ResultadoEstado(disponible=(aria == "true"), detalle=f"aria={aria}")

        try:
            marcado = await toggle.is_checked()
            return ResultadoEstado(disponible=marcado, detalle="checkbox")
        except Exception:
            clases = await toggle.get_attribute("class") or ""
            return ResultadoEstado(disponible=False, detalle=f"class={clases}")

    async def apagar(self, nombre_remoto: str, por_hoy: bool = True) -> bool:
        estado = await self.leer_estado(nombre_remoto)
        if estado is None:
            return False
        if not estado.disponible:
            log.info("'%s' ya estaba apagado, no toco nada", nombre_remoto)
            return True

        fila = self._fila(nombre_remoto)
        await self._click_toggle(fila)
        await self.page.wait_for_timeout(1500)

        # El popup ofrece las dos opciones
        opcion = self.TXT_POR_HOY if por_hoy else self.TXT_INDEFINIDO
        try:
            await self.clickear(self.page.get_by_text(opcion),
                                que=f"opcion {opcion.pattern}")
        except Exception:
            # No sirve saber que no encontramos el texto: lo que hace falta
            # es saber que decia el popup que si se abrio.
            log.error("No encontre %s en el popup. Lo que hay abierto dice: %s",
                      opcion.pattern, await self.texto_overlay() or "(nada abierto)")
            await self.page.keyboard.press("Escape")
            return False

        await self.page.wait_for_timeout(3000)
        return await self._confirmar(nombre_remoto, esperado_disponible=False)

    async def prender(self, nombre_remoto: str) -> bool:
        estado = await self.leer_estado(nombre_remoto)
        if estado is None:
            return False
        if estado.disponible:
            log.info("'%s' ya estaba prendido, no toco nada", nombre_remoto)
            return True

        fila = self._fila(nombre_remoto)
        await self._click_toggle(fila)
        await self.page.wait_for_timeout(2000)

        # CONFIRMADO EN VIVO (2026-07-27, op#17): prender NO abre
        # ningun popup. El click sobre el toggle apagado lo prende directo y
        # queda guardado; la relectura despues de recargar lo encontro
        # prendido. El popup de dos opciones es solo del lado de apagar,
        # porque ahi hay que elegir "por hoy" o "indefinidamente".
        return await self._confirmar(nombre_remoto, esperado_disponible=True)
