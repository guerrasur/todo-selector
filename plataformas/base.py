"""Contrato que tiene que cumplir cada plataforma (Rappi, PedidosYa).

CADA PLATAFORMA IMPLEMENTA ESTOS 4 METODOS. Nada mas.
El worker no sabe nada de selectores: solo llama estos metodos.
"""

import logging
import re
import unicodedata
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("plataformas")


def plano(texto: str) -> str:
    """Sin tildes, en minusculas y con los espacios colapsados.

    Para COMPARAR textos del portal, nunca para buscarlos ni para guardarlos.
    Existe porque un texto que se ve igual puede no ser el mismo string:
    'Sólo por hoy' y 'Solo por hoy' se leen identicos en pantalla y un
    match exacto falla con uno de los dos. Es el mismo criterio que usa el
    buscador de la pantalla (`plano()` en static/index.html).
    """
    descompuesto = unicodedata.normalize("NFD", texto or "")
    sin_tildes = "".join(c for c in descompuesto
                         if unicodedata.category(c) != "Mn")
    return " ".join(sin_tildes.split()).lower()


def _resumen(e: Exception, limite: int = 90) -> str:
    """El error en una linea, para meterlo en un log sin volcar el call log."""
    return " ".join(str(e).split())[:limite]


class NombreAmbiguo(Exception):
    """El nombre del catalogo apunta a mas de un producto del portal.

    No es un error de red ni algo que un reintento pueda arreglar: hay que
    corregir el alias. Se distingue del resto para que la operacion termine
    ahi, con un mensaje que diga que hacer, en vez de gastar 3 intentos
    clickeando cualquiera de los dos.
    """


@dataclass
class ResultadoEstado:
    """Lo que devuelve leer_estado()."""
    disponible: bool          # True = prendido en la plataforma
    detalle: str = ""         # texto crudo util para debug


@dataclass
class ResultadoTienda:
    """Lo que devuelve leer_estado_tienda(): la TIENDA entera, no un producto."""
    abierta: bool             # True = esta tomando pedidos ahora
    detalle: str = ""         # texto crudo del portal ("open", "Suspendida", ...)


@dataclass
class Diagnostico:
    """Como quedo el elemento que no se pudo clickear.

    Los booleanos NO son decoracion del log: cada uno habilita un peldaño
    distinto de clickear().
    """
    texto: str = ""             # lo que se escribe en el log
    despejado: bool = False     # visible y NADA lo tapa -> se puede forzar
    tapa_un_ancestro: bool = False   # lo tapa un ancestro SUYO -> destapar
    # Si el target (o un hijo suyo) aparece en su PROPIA pila de hit test.
    # False = no lo tapa nadie: directamente no es clickeable en ese punto
    # (recortado por el overflow de un ancestro, o pointer-events:none
    # propio). Ahi no hay nada que destapar ni a donde correrse, y el log
    # tiene que decir eso y no "algo lo tapa". Arranca en True: si el
    # diagnostico no pudo correr, no se afirma lo que no se vio (regla 8).
    alcanzable: bool = True


class PlataformaBase(ABC):
    """Cada implementacion maneja UNA pestaña del navegador compartido."""

    nombre: str = "base"
    url_menu: str = ""

    def __init__(self, page):
        """page = pagina de Playwright dedicada a esta plataforma."""
        self.page = page
        # Por que la ultima lectura de estado de tienda no pudo afirmar
        # nada. Vacio = no hay nada que explicar. Un "sin datos" mudo no
        # distingue "no encontre el texto" de "no se cual de las tiendas
        # sos", y son arreglos distintos (ver leer_estado_tienda).
        self.diagnostico_tienda: dict = {}

    # AGREGADO (no toca el contrato de los 4 metodos): si faltan los datos
    # de la sucursal, no hay a donde navegar. Sin esto la app abria una
    # pestaña en una URL incompleta y despues decia "sesion caida", que le
    # manda al usuario a loguearse cuando el problema era otro.
    @property
    def configurado(self) -> bool:
        return True

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

    # ---------- Opcional (no rompe el contrato de los 4 de arriba) ----------

    async def leer_estado_tienda(self) -> Optional[ResultadoTienda]:
        """Si la TIENDA entera esta tomando pedidos ahora. Solo lectura.

        A proposito no hay forma de abrir/cerrar la tienda desde aca: el
        usuario solo pidio VER el estado, no manejarlo (ver conversacion del
        2026-07-30). Cada plataforma expone esto de forma distinta (o
        todavia no lo expone), asi que el default es "no se". Devolver None
        en vez de adivinar es la misma regla que en leer_estado(): no
        afirmar un estado que no se pudo leer de verdad.
        """
        return None

    async def en_verificacion(self) -> bool:
        """La pantalla que hay AHORA, ¿es una verificacion que hace el usuario?

        Algunos portales piden, cada tanto y ademas del login, un codigo de
        verificacion que llega por mail o SMS. Eso lo resuelve una persona,
        puede llevar varios minutos, y RECARGAR O NAVEGAR EN EL MEDIO INVALIDA
        EL CODIGO: hay que empezar de nuevo.

        Reglas de este metodo, para cualquier plataforma que lo implemente:

          - NO NAVEGA NI RECARGA. Mira lo que ya esta en la pestaña. Si para
            contestar hubiera que ir a algun lado, ya rompio lo que viene a
            proteger.
          - Ante la duda, False. Un falso positivo congela la plataforma
            hasta que alguien apriete el boton en la pantalla.
          - No es la defensa principal: la que tiene que funcionar si o si es
            el boton manual (worker.empezar_verificacion). Esto solo le
            ahorra el paso al usuario cuando acierta.

        Default: no. PedidosYa se reloguea solo y no pasa por esto.
        """
        return False

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

    # Donde vive lo que el portal abre por encima. No alcanza con los dos
    # primeros: el popup de disponibilidad de Rappi no es un <dialog> ni un
    # overlay de Angular sino un portal de floating-ui, asi que este metodo
    # contestaba "(nada)" con el popup abierto adelante (log del 2026-08-03).
    # Un diagnostico que dice "no habia nada" cuando SI habia manda a buscar
    # el problema al lugar equivocado.
    SELECTORES_OVERLAY = (
        ".cdk-overlay-container",
        "[role='dialog']",
        "[data-floating-ui-portal]",
        "[role='menu']",
        "[role='listbox']",
    )

    async def texto_overlay(self, limite: int = 500) -> str:
        """Que dice el dialogo que hay abierto, si hay alguno.

        Cuando no encontramos un boton dentro de un popup, lo unico util es
        saber que decia el popup que si estaba abierto.
        """
        for selector in self.SELECTORES_OVERLAY:
            try:
                cont = self.visible(self.page.locator(selector))
                if await cont.count() == 0:
                    continue
                texto = await cont.first.inner_text()
            except Exception:
                continue
            texto = " | ".join(l.strip() for l in texto.split("\n") if l.strip())
            if texto:
                return texto[:limite]
        return ""

    # Lo que el portal deja flotando por encima y se come los clicks sin
    # ser parte de la UI: overlays decorativos, franjas de hover. Cada
    # plataforma declara los suyos; vacio = no hay nada que hacer.
    SELECTORES_ESTORBO: tuple = ()

    async def neutralizar_estorbos(self):
        """Le saca los clicks de encima a los overlays decorativos.

        No los oculta ni los borra: solo `pointer-events: none`, asi la
        pagina se ve igual y el click llega al elemento de abajo.

        ESTO NO PUEDE CAUSAR UN CLICK EQUIVOCADO. Playwright sigue
        verificando que el que recibe el click sea nuestro elemento: si
        despues de esto el destino sigue estando mal, el click falla igual
        y se cae al fallback. Lo unico que cambia es que un adorno deja de
        interceptar.

        Hay que rehacerlo despues de cada navegacion (el <style> se va con
        la pagina), por eso se llama desde asegurar_sesion().
        """
        if not self.SELECTORES_ESTORBO:
            return
        css = (", ".join(self.SELECTORES_ESTORBO) +
               " { pointer-events: none !important; }")
        try:
            await self.page.add_style_tag(content=css)
        except Exception as e:
            # Un adorno que sigue estorbando no justifica romper la
            # operacion: el camino viejo (fallback) sigue estando.
            log.warning("%s: no pude neutralizar los estorbos: %s",
                        self.nombre, " ".join(str(e).split())[:100])

    def visible(self, locator):
        """El mismo locator, quedandose solo con lo que se ve.

        CONFIRMADO POR LOG (2026-08-03): el radio 'Solo por hoy' de Rappi
        matcheaba UN elemento y era invisible —el dialogo todavia no habia
        montado el de verdad—, asi que el `.first` de siempre clickeaba un
        fantasma. Buscar entre lo visible es lo que hace un usuario.
        """
        return locator.locator("visible=true")

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
    #
    # Y NO ALCANZA CON .click() (log del 2026-08-05): el toggle de Rappi se
    # prendia por este camino pero el popup de "hasta cuando" no se abria
    # nunca ("Opciones que vi: (ninguna)"). Prender lo dispara el `change`
    # del <input>, que la activacion nativa del <label> si propaga; el popup
    # lo abre un handler de floating-ui atado a pointerdown/mousedown, que
    # un .click() pelado no despierta. Por eso se manda la secuencia
    # completa: es lo que hace un mouse de verdad.
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

            const comun = {bubbles: true, cancelable: true, composed: true,
                           clientX: x, clientY: y, button: 0, buttons: 1};
            const tirar = (Clase, tipo, extra) => {
                try {
                    objetivo.dispatchEvent(new Clase(tipo, {...comun, ...extra}));
                } catch (e) { /* el navegador no conoce ese constructor */ }
            };
            tirar(PointerEvent, 'pointerdown', {pointerId: 1, isPrimary: true,
                                                pointerType: 'mouse'});
            tirar(MouseEvent, 'mousedown', {});
            tirar(PointerEvent, 'pointerup', {pointerId: 1, isPrimary: true,
                                              pointerType: 'mouse', buttons: 0});
            tirar(MouseEvent, 'mouseup', {buttons: 0});
            // El .click() nativo va ultimo y se deja tal cual: es el que
            // dispara la activacion del <label> y lo que ya venia andando.
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

    # Como nombrar un elemento en el log. Se comparte entre los scripts.
    JS_DESC = """
        const desc = n => {
            const t = n.tagName.toLowerCase();
            const id = n.getAttribute('data-testid');
            if (id) return `${t}[data-testid=${id}]`;
            const c = (n.getAttribute('class') || '').trim().split(/\\s+/)[0];
            return c ? `${t}.${c}` : t;
        };
    """

    # Que hay ARRIBA del centro del target. Usa elementsFromPoint (PLURAL):
    # devuelve la pila ENTERA de una sola llamada, no solo el de mas arriba.
    #
    # POR QUE LA PILA Y NO EL PRIMERO (log del 2026-08-05): destapando de a
    # una capa, cada vuelta contestaba un ancestro distinto y a las 3 nos
    # quedabamos sin intentos. Con la pila entera se ve de una cuantos son,
    # y sobre todo se puede contestar la pregunta que antes no se podia:
    #
    #   ¿aparece el target en su PROPIA pila?
    #
    # Si no aparece, no lo tapa nada: no es hit-testable en ese punto (lo
    # recorta el overflow de un ancestro, o tiene pointer-events:none). Ahi
    # elementFromPoint contestaba el primer ancestro que si lo es, y eso se
    # leia como "un ancestro lo esta tapando" — dos problemas con arreglos
    # opuestos que se veian igual.
    #
    # Devuelve {desc, propio, ancestro, alcanzable, encima}. Los booleanos
    # deciden por que peldaño sigue clickear(), asi que no son para el log:
    #   propio     -> nada lo tapa, se puede forzar.
    #   ancestro   -> lo tapa un ANCESTRO suyo (ver JS_DESTAPAR).
    #   alcanzable -> el target participa de su propio hit test.
    JS_QUIEN_TAPA = f"""
        el => {{
            {JS_DESC}
            const r = el.getBoundingClientRect();
            const x = r.left + r.width / 2, y = r.top + r.height / 2;
            const pila = document.elementsFromPoint(x, y);
            if (!pila.length) return {{desc: "(nadie: el centro cae fuera de la ventana)",
                                       propio: false, ancestro: false,
                                       alcanzable: false, encima: []}};
            const arriba = pila[0];
            // El target cuenta como alcanzado tambien si el que contesta es
            // un hijo suyo: el click igual le llega, porque los eventos suben.
            const i = pila.findIndex(n => n === el || el.contains(n));
            const encima = (i < 0 ? pila : pila.slice(0, i));
            return {{desc: desc(arriba),
                     propio: el === arriba || el.contains(arriba),
                     ancestro: arriba !== el && arriba.contains(el),
                     alcanzable: i >= 0,
                     encima: encima.slice(0, 8).map(desc)}};
        }}
    """

    # Le saca los clicks de encima al ANCESTRO que esta tapando al target.
    #
    # POR QUE ES SEGURO (log del 2026-08-05): el click sobre el toggle de
    # Rappi fallaba con "encima=ul[data-testid=menu-categories]", y ese <ul>
    # es un ANCESTRO del toggle. Que un ancestro gane elementFromPoint sobre
    # el centro de su propio descendiente solo puede pasar por decoracion:
    # un pseudo-elemento (::before/::after se reportan como el elemento que
    # los origina) o un fondo pintado por encima. UI de verdad "arriba" no
    # puede ser: estaria adentro del target. Por eso este caso se destapa y
    # el del header pegajoso (que NO es ancestro) no se toca.
    #
    # Se hace en UNA pasada, con la pila entera. Antes se destapaba de a una
    # capa y se reintentaba, hasta CAPAS_A_DESTAPAR: el log del 2026-08-05
    # gasto las 3 (ul[data-testid=menu-categories], div.sc-izEbhJ,
    # div.sc-izEbhJ) y el toggle seguia tapado. El limite era un numero
    # inventado; con elementsFromPoint no hace falta ninguno.
    #
    # Se filtra a los ancestros A PROPOSITO: lo que tapa y no es ancestro es
    # UI de verdad (el header pegajoso de categoria) y no se toca, aunque
    # este en la misma pila. Si queda algo asi, el click normal de despues
    # va a fallar igual y seguimos al peldaño que corresponde.
    #
    # Se guarda lo que habia para devolverlo tal cual, y el target se vuelve
    # a habilitar a mano: pointer-events se HEREDA, asi que apagarlo en los
    # ancestros apagaria tambien el toggle que queremos clickear.
    JS_DESTAPAR = f"""
        el => {{
            {JS_DESC}
            const r = el.getBoundingClientRect();
            const x = r.left + r.width / 2, y = r.top + r.height / 2;
            const pila = document.elementsFromPoint(x, y);
            const i = pila.findIndex(n => n === el || el.contains(n));
            const encima = (i < 0 ? pila : pila.slice(0, i));
            const objetivos = encima.filter(n => n !== el && n.contains(el));
            if (!objetivos.length) return [];

            const guardar = n => ({{
                nodo: n,
                valor: n.style.getPropertyValue('pointer-events'),
                prioridad: n.style.getPropertyPriority('pointer-events'),
            }});
            window.__tsDestapado = window.__tsDestapado || [];
            for (const n of objetivos) window.__tsDestapado.push(guardar(n));
            window.__tsDestapado.push(guardar(el));

            for (const n of objetivos) {{
                n.style.setProperty('pointer-events', 'none', 'important');
            }}
            el.style.setProperty('pointer-events', 'auto', 'important');

            return objetivos.map(desc);
        }}
    """

    # Deja todo como estaba. Corre SIEMPRE (finally): dejar media pagina sin
    # pointer-events seria rompersela al usuario, que mira esta misma ventana.
    JS_DESTAPAR_DESHACER = """
        () => {
            const guardados = window.__tsDestapado || [];
            for (const g of guardados.reverse()) {
                if (g.valor) {
                    g.nodo.style.setProperty('pointer-events', g.valor, g.prioridad);
                } else {
                    g.nodo.style.removeProperty('pointer-events');
                }
            }
            window.__tsDestapado = [];
            return guardados.length;
        }
    """

    # Corre el elemento hacia abajo dentro del contenedor que scrollea, para
    # sacarlo de atras de un header pegajoso. Es el "scrolleá un poco y
    # volve a intentar" que al usuario le funciona a mano: scrollIntoView
    # con block:'center' centra dentro del contenedor interno, y ese centro
    # puede caer igual debajo del header (caja@1210,340 en el log).
    JS_BAJAR_UN_POCO = """
        (el, pixeles) => {
            let cont = el.parentElement;
            while (cont && cont !== document.body) {
                const s = getComputedStyle(cont);
                if ((s.overflowY === 'auto' || s.overflowY === 'scroll') &&
                    cont.scrollHeight > cont.clientHeight) break;
                cont = cont.parentElement;
            }
            const antes = el.getBoundingClientRect().top;
            if (cont && cont !== document.body) cont.scrollTop -= pixeles;
            else window.scrollBy(0, -pixeles);
            return Math.round(el.getBoundingClientRect().top - antes);
        }
    """

    # Lo que el call log repite en cada reintento y no explica nada.
    RUIDO_DEL_CALL_LOG = re.compile(
        r"(waiting \d+ms|retrying click action|attempting click action"
        r"|waiting for element to be visible, enabled and stable"
        r"|element is visible, enabled and stable"
        r"|scrolling into view|done scrolling)")

    @classmethod
    def _motivo_del_click(cls, error: Exception) -> str:
        """El motivo de accionabilidad que Playwright esconde en el call log.

        HISTORIA: hasta el 2026-08-03 este error se recortaba a 110
        caracteres, que alcanzan justo para el "Timeout Xms exceeded" y el
        principio del locator, y se comian el motivo. Por eso `TRASPASO.md`
        quedo escrito con la hipotesis de que el locator no resolvia, que
        no puede ser: clickear() hace un evaluate() sobre el mismo locator
        ANTES del click, y ese evaluate no falla.

        El motivo real viene mas abajo, en las lineas del "Call log" que
        arrancan con "-": "element is not visible", "element intercepts
        pointer events", "element is not stable". Playwright repite la
        misma linea en cada reintento, asi que se deduplica conservando el
        orden; volcar el mensaje entero son decenas de lineas iguales.
        """
        crudo = str(error)
        cabeza = " ".join(crudo.split("\n")[0].split())[:120]

        vistas, motivos = set(), []
        for linea in crudo.split("\n"):
            linea = " ".join(linea.split())
            if not linea.startswith("- "):
                continue
            linea = linea[2:]
            if not linea or cls.RUIDO_DEL_CALL_LOG.match(linea):
                # El final del call log son puros reintentos y esperas: si
                # entran, empujan afuera justo la linea que dice por que.
                continue
            # Se deduplica ignorando los numeros: "retrying click action,
            # attempt #2" y "#3" son la misma linea repitiendose.
            clave = re.sub(r"\d+", "#", linea)
            if clave not in vistas:
                vistas.add(clave)
                motivos.append(linea)

        if not motivos:
            return cabeza
        # Las ultimas son las que explican por que se agoto el timeout; las
        # primeras son el "waiting for locator" de siempre. Se recorta CADA
        # linea y no el total: el locator de PedidosYa solo son 250
        # caracteres y se comia justo el motivo, que va al final.
        return f"{cabeza} | call log: " + " ; ".join(m[:130] for m in motivos[-4:])

    async def _diagnosticar(self, locator) -> Diagnostico:
        """Como esta el elemento que no se pudo clickear.

        Ademas del texto para el log, contesta las preguntas que deciden
        como sigue clickear(): si esta despejado (visible y sin nada encima,
        se puede forzar), si lo tapa un ancestro suyo (es decoracion, se
        puede destapar) y si el target aparece en su propia pila de hit test
        (si no aparece, no lo tapa nada: no es clickeable ahi, y ni destapar
        ni correrse sirven).

        Se llama DOS veces cuando hay destapado de por medio: la foto de
        antes ya no describe la pagina despues de neutralizar tres
        ancestros, y los peldaños que siguen se deciden con esto.

        Corre unicamente cuando el click ya fallo, asi que puede pagar unas
        consultas al DOM. Nunca puede tirar: un diagnostico que explota
        romperia una operacion que igual va a seguir por el fallback JS.
        """
        try:
            partes = [f"count={await locator.count()}"]
        except Exception as e:
            return Diagnostico(
                texto=f"(no pude diagnosticar: {' '.join(str(e).split())[:80]})")

        objetivo = locator.first
        es_visible, propio, ancestro, alcanzable = False, False, False, True
        # Fabricas y no corrutinas ya creadas: si una falla, las que
        # quedaban sin await tirarian "coroutine was never awaited".
        for etiqueta, hacer in (
            ("visible", lambda: objetivo.is_visible(timeout=1000)),
            ("caja", lambda: objetivo.bounding_box(timeout=1000)),
            ("encima", lambda: objetivo.evaluate(self.JS_QUIEN_TAPA,
                                                 timeout=1000)),
        ):
            try:
                valor = await hacer()
            except Exception as e:
                valor = f"? ({' '.join(str(e).split())[:60]})"
            if etiqueta == "visible":
                es_visible = valor is True
            elif etiqueta == "caja" and isinstance(valor, dict):
                valor = (f"{valor['width']:.0f}x{valor['height']:.0f}"
                         f"@{valor['x']:.0f},{valor['y']:.0f}")
            elif etiqueta == "encima" and isinstance(valor, dict):
                propio = bool(valor.get("propio"))
                ancestro = bool(valor.get("ancestro"))
                alcanzable = bool(valor.get("alcanzable"))
                pila = valor.get("encima") or []
                if propio:
                    valor = valor["desc"] + " (es el target o un hijo suyo)"
                elif not alcanzable:
                    # El caso que antes se leia como "lo tapa un ancestro" y
                    # mandaba a destapar capas para siempre.
                    valor = (f"{valor['desc']}, y el target NO aparece en su "
                             f"propia pila: no lo tapa nadie, no es clickeable "
                             f"en ese punto (lo recorta un overflow, o tiene "
                             f"pointer-events:none)")
                else:
                    valor = (" > ".join(pila) or valor["desc"]) + (
                        f" ({len(pila)} encima del target"
                        + (", el de arriba es un ancestro suyo)" if ancestro
                           else ")"))
            partes.append(f"{etiqueta}={valor}")
        return Diagnostico(texto=", ".join(partes),
                           despejado=(es_visible and propio),
                           tapa_un_ancestro=(es_visible and ancestro),
                           alcanzable=alcanzable)

    # Como se sube del texto del producto a su tarjeta/fila (XPATH_TARJETA),
    # y que la identifica: un atributo de la tarjeta misma, o de algun
    # elemento de adentro si el id no esta en la tarjeta (SELECTOR_ID_TARJETA
    # vacio = la tarjeta misma). Lo declara cada plataforma; se usa para
    # localizar (_tarjeta/_fila) y para detectar ambiguedad peligrosa.
    XPATH_TARJETA: str = ""
    SELECTOR_ID_TARJETA: str = ""
    ATRIBUTO_ID_TARJETA: str = ""

    def texto_exacto(self, nombre_remoto: str):
        """Los elementos cuyo texto es exactamente el nombre del producto.

        exact=True no es opcional: "Tarta de verdura" es prefijo de "Tarta
        de verdura chica" y sin esto se apaga el plato equivocado (regla 3).
        """
        return self.page.get_by_text(nombre_remoto, exact=True)

    async def tarjetas_del_nombre(self, nombre_remoto: str) -> list:
        """Los ids de las tarjetas distintas a las que llega ese nombre.

        Dos matches del mismo texto NO son necesariamente un problema: el
        nombre puede aparecer dos veces DENTRO de una tarjeta (titulo y
        algun rotulo). Es un problema cuando caen en DOS tarjetas: ahi el
        `.first` de siempre elige una al azar, y apagar la equivocada es
        indistinguible de un bug (regla 3 del CLAUDE.md).

        Devuelve la lista de ids distintos, en orden. Vacia si no se pudo
        averiguar, que se trata como "no se puede afirmar que haya lio".
        """
        if not (self.XPATH_TARJETA and self.ATRIBUTO_ID_TARJETA):
            return []

        textos = self.texto_exacto(nombre_remoto)
        try:
            cuantos = await textos.count()
        except Exception:
            return []

        ids = []
        for i in range(min(cuantos, 10)):
            try:
                quien = textos.nth(i).locator(self.XPATH_TARJETA).first
                if self.SELECTOR_ID_TARJETA:
                    quien = quien.locator(self.SELECTOR_ID_TARJETA).first
                ident = await quien.get_attribute(self.ATRIBUTO_ID_TARJETA,
                                                  timeout=1000)
            except Exception:
                continue
            if ident and ident not in ids:
                ids.append(ident)
        return ids

    async def revisar_ambiguedad(self, nombre_remoto: str):
        """Tira NombreAmbiguo si el nombre llega a dos productos distintos.

        CONFIRMADO EN VIVO (2026-08-03): en Rappi Comun 'Agua con gas'
        matchea 2 elementos con exact=True. Si los dos caen en la misma
        tarjeta da igual cual se agarre; si caen en dos, no hay forma de
        saber cual quiso el usuario, y elegir a ciegas es exactamente el
        bug que se esta tratando de evitar. Un apagado que no ocurre y se
        ve en rojo es mejor que uno que cae en el plato equivocado.
        """
        ids = await self.tarjetas_del_nombre(nombre_remoto)
        if len(ids) <= 1:
            return

        log.error("%s: '%s' aparece en %s productos distintos del portal "
                  "(%s). No toco ninguno: no hay forma de saber cual es.",
                  self.nombre, nombre_remoto, len(ids), ", ".join(ids[:4]))
        raise NombreAmbiguo(
            f"'{nombre_remoto}' aparece en {len(ids)} productos distintos de "
            f"{self.nombre}. Corregí el nombre en la pantalla Carta para que "
            f"apunte a uno solo.")

    async def clickear(self, locator, timeout: int = 8000, que: str = "elemento",
                       profundo: bool = False) -> bool:
        """Click que aguanta lo que los portales dejan flotando por encima.

        CONFIRMADO POR LOG (2026-07-27): en Rappi el header pegajoso de
        categoria y la franja `menu-categories-hoverable-gap` se comen el
        click. Playwright scrollea el elemento a la vista, algo le queda
        encima, y reintenta hasta agotar el timeout de 30s.

        Las defensas, en orden. El diagnostico del click fallado dice cual
        corresponde, y todas menos la ultima terminan en un click de VERDAD.
          1. Centrar el elemento en la pantalla (arriba esta el header,
             abajo la franja) y clickear normal, con timeout corto.
          2. Si lo tapan ANCESTROS suyos, neutralizarlos TODOS de una y
             reintentar. Un ancestro no puede estar legitimamente por encima
             de su propio hijo: es decoracion.
          3. Si NADA lo tapa, clickear forzado. Saltea los chequeos de
             accionabilidad de Playwright pero sigue siendo un evento de
             mouse de verdad en la posicion del elemento, asi que es fiel.
             Solo se usa cuando esta despejado: si algo tapa, forzar seria
             clickear a ciegas lo que haya encima, que es justo lo que no se
             quiere.
          4. Si lo tapa algo que NO es ancestro (UI de verdad, pegajosa),
             correrse y reintentar.
          5. Recien ahi, click por JS, que no mira nada. Es el ultimo plan.

        El 3 y el 4 corren tambien ADENTRO del 2, con el destapado puesto y
        contra un diagnostico nuevo: neutralizar los ancestros cambia la
        pagina, y el 4 corriendo sobre la pila ya restaurada era trabajo
        tirado (log del 2026-08-05).

        Hay un caso que no tiene peldaño y que hasta el 2026-08-05 se
        confundia con el 2: que el target no aparezca en su PROPIA pila de
        hit test. Ahi no lo tapa nada —lo recorta un overflow, o tiene
        pointer-events:none— y no hay nada que destapar ni a donde correrse.
        Se dice en el log y se va derecho al JS.

        Del 2 al 4 el timeout es TIMEOUT_REINTENTO y no el de arriba: son
        preguntas de "¿pasa el hit test ahora?", y con los 8 s de siempre un
        click que no entra por ningun lado costaba casi un minuto.

        Se usa para TODOS los clicks (toggle, opciones del popup, boton de
        confirmar): cualquiera de ellos puede quedar tapado.

        Devuelve True si entro un click DE VERDAD (normal o forzado) y
        False si hubo que ir por JS. Al que llama le importa la diferencia:
        el fallback JS no siempre dispara lo mismo que un click real, asi
        que un resultado inesperado despues de un False todavia puede ser
        culpa del click. El forzado no tiene ese problema.

        POR QUE EL PELDAÑO 2 (log del 2026-08-05): en Rappi el toggle
        fallaba con "encima=ul[data-testid=menu-categories]", que es un
        ANCESTRO del toggle: decoracion pintada por encima de su propio
        hijo. Ahi se le sacan los clicks a los ancestros, entra el click de
        verdad, y se deja todo como estaba. Ver JS_DESTAPAR. Son TODOS de
        una: destapando de a uno, el mismo log gasto las 3 capas que habia
        y el toggle seguia tapado.

        POR QUE EL PELDAÑO 3 (log del 2026-08-03): en PedidosYa el toggle
        fallaba con "element is not enabled" teniendo el camino libre —el
        <input> de Angular Material es cdk-visually-hidden y Playwright lo
        da por deshabilitado, pero el toggle anda—. Ahi el click forzado
        entra y ahorra los 8-10 s del timeout, sin caer en el JS.

        POR QUE EL PELDAÑO 4: lo que tapa y NO es ancestro es UI de verdad
        (el header pegajoso de categoria de Rappi, que a proposito no se
        neutraliza). A eso no hay que desactivarlo sino correrse: se baja el
        elemento dentro de su contenedor y se reintenta, que es lo que hace
        el usuario a mano.
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
            diag = await self._diagnosticar(objetivo)
            motivo = self._motivo_del_click(e)

        if diag.tapa_un_ancestro:
            # Los peldaños que siguen corren ADENTRO del destapado. Antes el
            # destapado se restauraba al salir de _click_destapando() y
            # "corriendose" peleaba de nuevo contra la pila entera: en el log
            # del 2026-08-05 se ven las dos lineas seguidas, y la segunda
            # trabajando sobre la pagina ya restaurada.
            async with self._destapado(objetivo) as destapados:
                if destapados:
                    try:
                        await objetivo.click(timeout=self.TIMEOUT_REINTENTO)
                        log.info("%s: el click sobre %s entro despues de "
                                 "destapar %s", self.nombre, que,
                                 ", ".join(destapados))
                        return True
                    except Exception:
                        pass

                    # La foto de antes describe una pagina que ya no existe:
                    # se acaban de neutralizar N ancestros. Los peldaños que
                    # vienen se deciden con esta, no con aquella.
                    diag = await self._diagnosticar(objetivo)
                    entro, detalle = await self._forzar_o_correrse(objetivo, diag)
                    if entro:
                        log.info("%s: el click sobre %s entro despues de "
                                 "destapar %s y %s", self.nombre, que,
                                 ", ".join(destapados), detalle)
                        return True
                    motivo += (f" || destapando ({', '.join(destapados)})"
                               f" + {detalle}")
                else:
                    motivo += f" || destapando ({destapados.motivo})"
        else:
            entro, detalle = await self._forzar_o_correrse(objetivo, diag)
            if entro:
                # Con el motivo, que es lo que dice POR QUE no habia entrado
                # el normal: en PedidosYa este camino es el de todos los dias
                # ("element is not enabled" con el camino libre) y sin el
                # motivo el log no deja rastro de cual de los dos casos fue.
                log.info("%s: el click sobre %s entro despues de %s.\n"
                         "    motivo: %s\n    estado: %s",
                         self.nombre, que, detalle, motivo, diag.texto)
                return True
            motivo += f" || {detalle}"

        log.warning("%s: click normal sobre %s fallo. Voy por JS.\n"
                    "    motivo: %s\n"
                    "    estado: %s", self.nombre, que, motivo, diag.texto)
        await self.clickear_por_js(objetivo, profundo=profundo, timeout=timeout)
        return False

    # Los reintentos NO usan el timeout del click normal. El elemento ya esta
    # localizado y lo unico que se esta preguntando es si el hit test pasa
    # ahora: 2,5 s alcanzan de sobra. Con los 8 s de siempre, un click que no
    # entra por ningun lado pasaba de costar 8 s a costar casi 50, y lo que
    # el usuario reporto fue justamente que la app "se queda trabada".
    TIMEOUT_REINTENTO = 2500

    async def _forzar_o_correrse(self, objetivo, diag) -> tuple[bool, str]:
        """Los peldaños que dependen de QUE es lo que no deja clickear.

        Van juntos porque son excluyentes y los decide el mismo diagnostico.
        Devuelve (entro, que se hizo / por que no).
        """
        if diag.despejado:
            # Saltea los chequeos de accionabilidad pero sigue siendo un
            # evento de mouse de verdad en la posicion del elemento. Solo con
            # el camino libre: si algo tapa, forzar es clickear a ciegas lo
            # que haya encima.
            try:
                await objetivo.click(timeout=self.TIMEOUT_REINTENTO, force=True)
                return True, "forzarlo con el camino libre"
            except Exception as e:
                return False, f"forzado: {self._motivo_del_click(e)}"

        if not diag.alcanzable:
            # No hay nada que correr ni que destapar: el punto que Playwright
            # clickea no le pertenece al target. Decirlo con estas palabras
            # es la mitad del arreglo.
            return False, ("el target no aparece en su propia pila: no lo tapa "
                           "nada, no es clickeable en su centro")

        return await self._click_corriendose(objetivo)

    class _Destapados(list):
        """Los ancestros neutralizados, y por que no hubo ninguno.

        Es una lista para poder preguntarle `if destapados:` y recorrerla, y
        ademas guarda el motivo: "no habia nada que destapar" y "no pude
        destapar" son cosas distintas y las dos terminan en lista vacia.
        """
        motivo: str = "no habia ancestros que destapar"

    @asynccontextmanager
    async def _destapado(self, objetivo):
        """Neutraliza de una los ancestros que tapan, y restaura al salir.

        Todo lo que se intente adentro del `async with` ve la pagina
        destapada; al salir queda como estaba, pase lo que pase.

        El click de adentro sigue siendo el NORMAL de Playwright, con todos
        sus chequeos: si despues de destapar el que recibe el click sigue sin
        ser nuestro elemento, falla igual y seguimos al peldaño que viene.
        Destapar no puede hacer que se clickee otra cosa.
        """
        destapados = self._Destapados()
        try:
            try:
                quienes = await objetivo.evaluate(
                    self.JS_DESTAPAR, timeout=self.TIMEOUT_REINTENTO)
                destapados.extend(quienes or [])
            except Exception as e:
                destapados.motivo = f"no pude destapar: {_resumen(e)}"
            yield destapados
        finally:
            # Pase lo que pase la pagina queda como estaba: el usuario mira
            # esta misma ventana y la va a seguir usando a mano.
            try:
                await self.page.evaluate(self.JS_DESTAPAR_DESHACER)
            except Exception as e:
                log.warning("%s: no pude restaurar los pointer-events: %s",
                            self.nombre, _resumen(e))

    # Cuanto se corre el elemento cuando lo tapa algo pegajoso, y cuantas
    # veces. 120 px alcanzan para pasar un header de categoria.
    PIXELES_A_CORRER = 120
    VECES_A_CORRERSE = 2

    async def _click_corriendose(self, objetivo) -> tuple[bool, str]:
        """Baja el elemento dentro de su contenedor y reintenta el click."""
        for _ in range(self.VECES_A_CORRERSE):
            try:
                movido = await objetivo.evaluate(
                    self.JS_BAJAR_UN_POCO, self.PIXELES_A_CORRER,
                    timeout=self.TIMEOUT_REINTENTO)
            except Exception as e:
                return False, f"no pude scrollear: {_resumen(e)}"
            if not movido:
                return False, "el elemento no se movio (no hay a donde scrollear)"

            await self.page.wait_for_timeout(300)
            try:
                await objetivo.click(timeout=self.TIMEOUT_REINTENTO)
                return True, f"bajarlo {movido} px"
            except Exception:
                continue
        return False, f"no entro ni corriendolo {self.VECES_A_CORRERSE} veces"

    async def recargar_y_preparar(self, por_que: str = "",
                                  asentar: int = 1500) -> bool:
        """Recarga la pagina y la deja lista para volver a operar.

        Es lo que al usuario le funciona a mano cuando el portal se pone
        raro: recargar y reintentar. Rehace la preparacion del arranque
        (asegurar_sesion cierra popups, espera el menu y reinyecta
        neutralizar_estorbos, que no sobrevive a una navegacion) en vez de
        dormir un rato fijo y esperar lo mejor.

        Nunca tira: se llama en caminos de error, donde una excepcion aca
        taparia el error de verdad. Devuelve si la pagina quedo lista.
        """
        try:
            await self.page.reload(wait_until="domcontentloaded")
            lista = await self.asegurar_sesion()
        except Exception as e:
            log.warning("%s: error recargando la pagina%s: %s", self.nombre,
                        f" para {por_que}" if por_que else "", _resumen(e, 120))
            return False

        if not lista:
            log.warning("%s: al recargar%s, la pagina no quedo lista",
                        self.nombre, f" para {por_que}" if por_que else "")

        await self.page.wait_for_timeout(asentar)
        return lista

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
        await self.recargar_y_preparar(por_que=f"reconfirmar '{nombre_remoto}'",
                                       asentar=asentar)

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

    # Por que un elemento no recibe el click, mirado desde el DOM y no desde
    # el error de Playwright. Devuelve la pila de hit test en su centro, la
    # cadena de ancestros con lo unico que puede estar estorbando
    # (pointer-events, position, z-index, overflow, transform) y si algun
    # ancestro lo esta RECORTANDO — que es el caso que el error de Playwright
    # nunca nombra y que se confundia con "algo lo tapa".
    JS_POR_QUE_NO_ENTRA = f"""
        el => {{
            {JS_DESC}
            const r = el.getBoundingClientRect();
            const x = r.left + r.width / 2, y = r.top + r.height / 2;
            const pila = document.elementsFromPoint(x, y).slice(0, 10).map(desc);

            const cadena = [];
            let recortado_por = null;
            let n = el.parentElement, prof = 0;
            while (n && n !== document.documentElement && prof < 12) {{
                const s = getComputedStyle(n);
                cadena.push({{
                    quien: desc(n),
                    pointer_events: s.pointerEvents,
                    position: s.position,
                    z_index: s.zIndex,
                    overflow: `${{s.overflowX}}/${{s.overflowY}}`,
                    transform: s.transform === 'none' ? '' : 'si',
                }});
                if (!recortado_por && s.overflow !== 'visible') {{
                    const c = n.getBoundingClientRect();
                    // El CENTRO del target es el punto que Playwright clickea:
                    // si cae afuera de la caja del contenedor que recorta, el
                    // click no le puede llegar por mas que se vea.
                    if (x < c.left || x > c.right || y < c.top || y > c.bottom) {{
                        recortado_por = desc(n);
                    }}
                }}
                n = n.parentElement; prof++;
            }}

            const mio = getComputedStyle(el);
            return {{
                quien: desc(el),
                caja: `${{Math.round(r.width)}}x${{Math.round(r.height)}}`
                      + `@${{Math.round(r.left)}},${{Math.round(r.top)}}`,
                pointer_events_propio: mio.pointerEvents,
                visibility: mio.visibility,
                pila_en_su_centro: pila,
                aparece_en_su_pila: document.elementsFromPoint(x, y)
                    .some(m => m === el || el.contains(m)),
                recortado_por: recortado_por,
                ancestros: cadena,
                html: el.outerHTML.slice(0, 1500),
            }};
        }}
    """

    async def por_que_no_entra(self, locator) -> dict:
        """Diagnostico: todo lo que hay alrededor de un elemento que no se
        deja clickear.

        Es para mirarlo a mano cuando el log ya no alcanza: dice quien esta
        en la pila del hit test, si el target participa de ella, si algun
        ancestro lo recorta, y como quedan los pointer-events de toda la
        cadena. Nunca tira: es diagnostico.
        """
        try:
            return await locator.first.evaluate(self.JS_POR_QUE_NO_ENTRA,
                                                timeout=3000)
        except Exception as e:
            return {"error": _resumen(e, 160)}

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

    async def leer_todos(self) -> dict:
        """{nombre_remoto: disponible} de TODA la carta, de una pasada.

        La app arrancaba sin saber nada: cada producto quedaba en
        "desconocido" hasta que vos tocaras un boton, asi que la pantalla no
        contestaba la pregunta mas basica, cual esta prendido.

        Esta implementacion sirve para cualquier plataforma porque se apoya
        en los dos metodos que ya estan confirmados. Si una puede leerlo mas
        rapido, que lo sobreescriba (PedidosYa lo hace: recorre las
        categorias una sola vez en vez de buscar producto por producto).
        """
        salida = {}
        for nombre in await self.listar_productos():
            if nombre in salida:
                continue
            estado = await self.leer_estado(nombre)
            if estado is not None:
                salida[nombre] = estado.disponible
        return salida

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
        encuentre nada. Buscando un fragmento con esto se ve como esta escrito
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
