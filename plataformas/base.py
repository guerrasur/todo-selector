"""Contrato que tiene que cumplir cada plataforma (Rappi, PedidosYa).

CADA PLATAFORMA IMPLEMENTA ESTOS 4 METODOS. Nada mas.
El worker no sabe nada de selectores: solo llama estos metodos.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


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
