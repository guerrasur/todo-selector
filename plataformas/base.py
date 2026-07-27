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

    async def ir_al_menu(self):
        """Navega a la pantalla del menu si no estamos ahi."""
        if self.url_menu and self.url_menu not in self.page.url:
            await self.page.goto(self.url_menu, wait_until="domcontentloaded")
            await self.page.wait_for_timeout(3000)

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
