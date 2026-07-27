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

    async def clickear(self, locator, timeout: int = 8000, que: str = "elemento"):
        """Click que aguanta lo que los portales dejan flotando por encima.

        CONFIRMADO POR LOG (2026-07-27): en Rappi el header pegajoso de
        categoria y la franja `menu-categories-hoverable-gap` se comen el
        click. Playwright scrollea el elemento a la vista, algo le queda
        encima, y reintenta hasta agotar el timeout de 30s.

        Dos defensas, en orden:
          1. Centrar el elemento en la pantalla (arriba esta el header,
             abajo la franja) y clickear normal, con timeout corto.
          2. Si igual no entra, HTMLElement.click(), que no mira que haya
             arriba. Es menos fiel a un click real, por eso es el plan B.

        Se usa para TODOS los clicks (toggle, opciones del popup, boton de
        confirmar): cualquiera de ellos puede quedar tapado.
        """
        objetivo = locator.first
        await objetivo.evaluate(
            "el => el.scrollIntoView({block: 'center', inline: 'center'})",
            timeout=timeout,
        )
        await self.page.wait_for_timeout(300)

        try:
            await objetivo.click(timeout=timeout)
        except Exception as e:
            log.warning("%s: click normal sobre %s fallo (%s). Voy por JS.",
                        self.nombre, que, " ".join(str(e).split())[:110])
            await objetivo.evaluate("el => el.click()", timeout=timeout)

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
