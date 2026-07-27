"""Contrato que tiene que cumplir cada plataforma (Rappi, PedidosYa).

CADA PLATAFORMA IMPLEMENTA ESTOS 4 METODOS. Nada mas.
El worker no sabe nada de selectores: solo llama estos metodos.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("plataformas")


@dataclass
class ResultadoEstado:
    """Lo que devuelve leer_estado()."""
    disponible: bool          # True = prendido en la plataforma
    detalle: str = ""         # texto crudo util para debug


class PlataformaBase(ABC):
    """Cada implementacion maneja UNA pestaña del navegador compartido."""

    nombre: str = "base"
    url_menu: str = ""

    def __init__(self, page):
        """page = pagina de Playwright dedicada a esta plataforma."""
        self.page = page

    # ---------- Lo que hay que implementar ----------

    @abstractmethod
    async def asegurar_sesion(self) -> bool:
        """Verifica que estemos logueados y en la pantalla del menu.

        Si la sesion expiro, devuelve False (la UI le avisa al usuario
        que se loguee a mano en la ventana del navegador).
        No intentamos loguear con credenciales guardadas: estas plataformas
        suelen tener 2FA y es mas seguro que el login sea manual una vez.
        """
        ...

    @abstractmethod
    async def leer_estado(self, nombre_remoto: str) -> Optional[ResultadoEstado]:
        """Lee si el producto esta disponible. None si no lo encuentra."""
        ...

    @abstractmethod
    async def apagar(self, nombre_remoto: str, por_hoy: bool = True) -> bool:
        """Apaga el producto. por_hoy=False significa indefinidamente.

        Devuelve True solo si pudo CONFIRMAR el cambio releyendo el estado.
        """
        ...

    @abstractmethod
    async def prender(self, nombre_remoto: str) -> bool:
        """Vuelve a poner el producto disponible. Confirma releyendo."""
        ...

    # ---------- Helpers comunes ----------

    def en_el_menu(self) -> bool:
        """Estamos parados en la pantalla del menu?

        Se chequea por partes y no comparando la URL entera porque los
        portales la reescriben: Rappi le agrega los storeIds de las cinco
        tiendas. Comparando el string completo NUNCA coincidia, asi que
        ir_al_menu() navegaba de nuevo en cada lectura. Eso era 30 recargas
        para verificar el catalogo, y navegaciones pisandose entre si
        (net::ERR_ABORTED en el log del 2026-07-27).
        """
        return bool(self.url_menu) and self.url_menu in self.page.url

    async def ir_al_menu(self):
        """Navega a la pantalla del menu si no estamos ahi."""
        if self.url_menu and not self.en_el_menu():
            await self.page.goto(self.url_menu, wait_until="domcontentloaded")
            await self.page.wait_for_timeout(3000)

    async def texto_overlay(self, limite: int = 500) -> str:
        """Que dice el dialogo que hay abierto, si hay alguno.

        Cuando no encontramos un boton dentro de un popup, lo unico util es
        saber que decia el popup que si estaba abierto.
        """
        for selector in (".cdk-overlay-container", "[role='dialog']"):
            try:
                cont = self.page.locator(selector)
                if await cont.count() == 0:
                    continue
                texto = await cont.first.inner_text()
            except Exception:
                continue
            texto = " | ".join(l.strip() for l in texto.split("\n") if l.strip())
            if texto:
                return texto[:limite]
        return ""

    # HTMLElement.click() sobre el elemento mismo. Alcanza cuando el que
    # escucha el click es ese elemento o alguno de sus padres.
    JS_CLICK = "el => el.click()"

    # Click por JS sobre el descendiente mas profundo que ocupa el centro
    # del elemento.
    #
    # CONFIRMADO POR LOG (2026-07-27): las tres categorias de PedidosYa se
    # clickearon por el fallback JS y NINGUNA cambio la lista de productos.
    # El motivo es que los eventos SUBEN pero no bajan: si el handler vive
    # en un hijo de <wk-menu-list-category-item>, un click disparado sobre
    # el custom element no lo despierta. Clickeando el hijo mas profundo el
    # evento sube por todos los niveles, asi que cubre las dos formas.
    JS_CLICK_PROFUNDO = """
        el => {
            const r = el.getBoundingClientRect();
            const x = r.left + r.width / 2, y = r.top + r.height / 2;
            let objetivo = el, mayor = -1;
            const mirar = (nodo, prof) => {
                const b = nodo.getBoundingClientRect();
                if (b.width > 0 && b.height > 0 &&
                    x >= b.left && x <= b.right &&
                    y >= b.top && y <= b.bottom && prof > mayor) {
                    mayor = prof;
                    objetivo = nodo;
                }
                for (const h of nodo.children) mirar(h, prof + 1);
            };
            mirar(el, 0);
            objetivo.click();
            return objetivo.tagName.toLowerCase();
        }
    """

    async def clickear_por_js(self, locator, profundo: bool = False,
                              timeout: int = 8000) -> str:
        """Dispara el click por JS, sin los chequeos de Playwright.

        No mira si algo esta tapando el elemento: por eso es el plan B de
        clickear(), y por eso tambien sirve para salir de un backdrop que se
        come los clicks. `profundo` decide si se clickea el elemento o su
        descendiente mas profundo (ver JS_CLICK_PROFUNDO).
        """
        js = self.JS_CLICK_PROFUNDO if profundo else self.JS_CLICK
        return await locator.first.evaluate(js, timeout=timeout)

    async def clickear(self, locator, timeout: int = 8000, que: str = "elemento",
                       profundo: bool = False) -> bool:
        """Click que aguanta lo que los portales dejan flotando por encima.

        CONFIRMADO POR LOG (2026-07-27): en Rappi el header pegajoso de
        categoria y la franja `menu-categories-hoverable-gap` se comen el
        click. Playwright scrollea el elemento a la vista, algo le queda
        encima, y reintenta hasta agotar el timeout de 30s.

        Dos defensas, en orden:
          1. Centrar el elemento en la pantalla (arriba esta el header,
             abajo la franja) y clickear normal, con timeout corto.
          2. Si igual no entra, click por JS, que no mira que haya arriba.
             Es menos fiel a un click real, por eso es el plan B.

        Se usa para TODOS los clicks (toggle, opciones del popup, boton de
        confirmar): cualquiera de ellos puede quedar tapado.

        Devuelve True si entro el click normal y False si hubo que ir por
        JS. Al que llama le importa la diferencia: el fallback JS no siempre
        dispara lo mismo que un click de verdad, asi que un resultado
        inesperado despues de un False todavia puede ser culpa del click.
        """
        objetivo = locator.first
        await objetivo.evaluate(
            "el => el.scrollIntoView({block: 'center', inline: 'center'})",
            timeout=timeout,
        )
        await self.page.wait_for_timeout(300)

        try:
            await objetivo.click(timeout=timeout)
            return True
        except Exception as e:
            log.warning("%s: click normal sobre %s fallo (%s). Voy por JS.",
                        self.nombre, que, " ".join(str(e).split())[:110])
            await self.clickear_por_js(objetivo, profundo=profundo, timeout=timeout)
            return False

    async def _confirmar(self, nombre_remoto: str, esperado_disponible: bool,
                         asentar: int = 1500) -> bool:
        """Recarga, deja la pagina lista y relee. No confiamos en el click.

        CONFIRMADO POR LOG (2026-07-27, op#17): esperar un rato fijo despues
        del reload NO alcanza en PedidosYa. La recarga vuelve a mostrar el
        popup de sonido, cuyo backdrop se come los clicks, y ademas deja el
        menu en la primera categoria: la relectura no encontro el producto y
        dio por fallada una operacion que SI habia entrado. El reintento la
        encontro prendida y termino en OK.

        Por eso aca se rehace la misma preparacion del arranque
        (asegurar_sesion: cierra popups y espera a que el menu exista) en
        vez de dormir y esperar lo mejor.
        """
        await self.page.reload(wait_until="domcontentloaded")

        try:
            if not await self.asegurar_sesion():
                log.warning("%s: al recargar para reconfirmar '%s', la pagina "
                            "no quedo lista", self.nombre, nombre_remoto)
        except Exception as e:
            log.warning("%s: error preparando la pagina para reconfirmar '%s': %s",
                        self.nombre, nombre_remoto, " ".join(str(e).split())[:120])

        await self.page.wait_for_timeout(asentar)

        estado = await self.leer_estado(nombre_remoto)

        # Distinguir los dos fallos importa: "no lo encontre" es un problema
        # de lectura (el cambio puede haber entrado igual) y "quedo al reves"
        # es un problema del portal, que a veces no guarda.
        if estado is None:
            log.warning("%s: no encontre '%s' al reconfirmar; no puedo decir si "
                        "el cambio entro", self.nombre, nombre_remoto)
            return False

        if estado.disponible != esperado_disponible:
            log.warning("%s: '%s' quedo %s y esperaba %s (%s)",
                        self.nombre, nombre_remoto,
                        "prendido" if estado.disponible else "apagado",
                        "prendido" if esperado_disponible else "apagado",
                        estado.detalle)
            return False

        return True

    # Elementos donde suele vivir la navegacion de categorias. La idea es
    # mirar todos y ver cual trae los nombres de las categorias, en vez de
    # adivinar como se cambia de seccion.
    CANDIDATOS_NAVEGACION = [
        "mat-expansion-panel-header",
        "[role='tab']",
        "[role='button']",
        "button",
        "nav a",
        "h1, h2, h3, h4",
        "li",
    ]

    async def estructura(self, por_selector: int = 30) -> dict:
        """Diagnostico: como esta armada la pantalla del menu.

        PedidosYa solo tiene en el DOM la categoria que esta a la vista (4
        toggles de 26 productos, medido 2026-07-27). Para llegar al resto
        hay que saber como se cambia de categoria, y esto lo muestra sin
        tener que suponerlo.
        """
        await self.ir_al_menu()

        salida = {}
        for selector in self.CANDIDATOS_NAVEGACION:
            try:
                loc = self.page.locator(selector)
                total = await loc.count()
            except Exception:
                continue
            if total == 0:
                continue

            textos = []
            for i in range(min(total, por_selector)):
                try:
                    texto = await loc.nth(i).inner_text()
                except Exception:
                    continue
                texto = " ".join(texto.split())[:60]
                if texto and texto not in textos:
                    textos.append(texto)
            salida[selector] = {"total": total, "textos": textos}

        return salida

    async def esqueleto(self, max_nodos: int = 400, max_texto: int = 45) -> list[str]:
        """Diagnostico: el arbol del DOM en una lista de lineas.

        Cuando no sabemos donde vive algo (la lista de categorias de
        PedidosYa, por ejemplo) y buscar por texto no sirve porque el
        portal esta en otro idioma, lo unico que resuelve es ver la
        estructura. Devuelve tag, id, clases y el texto propio de cada
        elemento, indentado por profundidad.
        """
        await self.ir_al_menu()
        return await self.page.evaluate(
            """([maxNodos, maxTexto]) => {
                const salida = [];
                const saltar = new Set(['SCRIPT', 'STYLE', 'SVG', 'PATH',
                                        'NOSCRIPT', 'HEAD', 'META', 'LINK']);
                const caminar = (el, prof) => {
                    if (salida.length >= maxNodos) return;
                    if (saltar.has(el.tagName)) return;

                    // solo el texto propio, no el de los hijos
                    let propio = '';
                    for (const n of el.childNodes) {
                        if (n.nodeType === 3) propio += n.textContent;
                    }
                    propio = propio.replace(/\\s+/g, ' ').trim().slice(0, maxTexto);

                    const id = el.id ? '#' + el.id : '';
                    const clases = (el.className && typeof el.className === 'string')
                        ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.')
                        : '';
                    const testid = el.dataset && el.dataset.testid
                        ? `[${el.dataset.testid.slice(0, 40)}]` : '';

                    salida.push('  '.repeat(Math.min(prof, 12)) +
                                el.tagName.toLowerCase() + id + clases + testid +
                                (propio ? '  "' + propio + '"' : ''));

                    for (const h of el.children) caminar(h, prof + 1);
                };
                caminar(document.body, 0);
                return salida;
            }""",
            [max_nodos, max_texto],
        )

    async def listar_productos(self) -> list[str]:
        """Todos los nombres de producto que la pagina esta mostrando.

        Hoy es diagnostico: contesta si un producto "no encontrado" no esta
        en el portal o si el portal simplemente no lo tiene renderizado.
        Es tambien el primer ladrillo para armar el catalogo leyendo las dos
        cartas en vez de mantenerlo a mano en seed.py.
        """
        return []

    async def inspeccionar(self, nombre_remoto: str) -> dict:
        """Diagnostico: el HTML crudo de la fila/tarjeta del producto.

        Es la forma mas directa de contestar por que un click no entra:
        muestra si el control esta `disabled`, con `aria-disabled`, dentro
        de un <fieldset disabled>, o que clases tiene en cada estado.
        Cada plataforma lo implementa con su propio localizador de fila.
        """
        return {}

    async def _html_de(self, locator, limite: int = 2500) -> dict:
        """Helper para inspeccionar(): outerHTML recortado de un locator."""
        if await locator.count() == 0:
            return {"encontrado": False}
        try:
            html = await locator.first.evaluate("el => el.outerHTML")
        except Exception as e:
            return {"encontrado": True, "error": str(e)}
        return {"encontrado": True, "html": html[:limite],
                "recortado": len(html) > limite}

    async def buscar_textos(self, fragmento: str, limite: int = 40) -> list[str]:
        """Diagnostico: textos visibles del portal que contienen 'fragmento'.

        Los nombres se buscan con exact=True, asi que una mayuscula o un
        guion de diferencia entre el catalogo y el portal hace que no se
        encuentre nada. Buscando "Coca" con esto se ve como esta escrito
        realmente el producto y se corrige el alias.
        """
        await self.ir_al_menu()
        loc = self.page.get_by_text(fragmento, exact=False)
        total = min(await loc.count(), limite)

        vistos = []
        for i in range(total):
            try:
                texto = (await loc.nth(i).inner_text()).strip()
            except Exception:
                continue
            if texto and texto not in vistos:
                vistos.append(texto)
        return vistos
