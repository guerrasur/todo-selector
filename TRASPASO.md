# Todo-Selector — traspaso de sesión (2026-07-29)

Pegá esto al arrancar la sesión nueva. Es todo lo que costó averiguar.

**Repo:** `guerrasur/todo-selector` (público) · todo mergeado a `main` hasta el
PR #24. El dueño tiene un **clon privado** con el historial viejo completo.

**LO PRIMERO QUE HAY QUE MIRAR:** quedó un paso a medias, el force-push que
limpia el historial. Ver «El historial de git» abajo.

App local (FastAPI + Playwright) que apaga/prende productos en PedidosYa y
Rappi desde una pantalla. Corre en `127.0.0.1:8001`.

---

## Estado: EN USO, andando en el local

Las cuatro operaciones corren en vivo contra los dos portales. Confirmado en
el log del 2026-07-28 13:24: las dos sesiones OK, lectura inicial de las dos
cartas, y dos `prender` seguidos que terminaron en OK.

| | leer la carta | apagar | prender |
|---|---|---|---|
| **PedidosYa** | ✅ la carta entera, recorriendo categorías | ✅ | ✅ (op#17, op#63) |
| **Rappi** | ✅ la carta entera | ✅ | ✅ (op#18, op#64) |

La tienda **Rappi Común** (opcional, `rappi_comun_store_id` en Ajustes) usa la
misma clase con otro `storeId` y otra pestaña. **En vivo todavía no se probó**:
el código es el mismo que el de Turbo, pero nadie la corrió contra el portal.

Queda un `TODO-SELECTOR` en `plataformas/rappi.py`: el HTML completo de la
tarjeta y el selector de la pantalla de sesión expirada.

## NO METAS DATOS DE UN LOCAL REAL EN EL REPO

El repo es público. El 2026-07-29 se sacó todo rastro del local que lo usa: su
carta, su id de menú de PedidosYa y su `brandId`/`storeId` de Rappi — del
código, de la documentación, de los comentarios y de las pruebas.

Para los ejemplos está la carta inventada de `pruebas/catalogo_ejemplo.py` y
`pruebas/carta_ejemplo.json`. No uses nombres ni ids reales en ningún lado, ni
siquiera en un comentario.

## El historial de git — QUEDÓ UN PASO SIN HACER

El **árbol** de `main` está limpio, pero su **historial** todavía tiene todo:
la carta vieja y los ids viven en los commits anteriores.

La reescritura está hecha y verificada, en la rama **`historial-limpio`**:

| | commits | árbol | historial |
|---|---|---|---|
| `main` | 54 | el bueno | el viejo, con los datos |
| `historial-limpio` | 52 | **idéntico** al de main | limpio |

`git diff main historial-limpio` no devuelve nada: son el mismo código con dos
historias distintas. (Dos commits menos porque, al aplicar el scrub a toda la
historia, el commit cosmético del PR #24 quedó vacío y `filter-repo` lo podó
junto con su merge. Correcto: ese cambio ya está incorporado más abajo.)

**Lo que falta es una sola línea**, y no se puede hacer con un PR — un merge
dejaría las dos historias como padres y los commits viejos seguirían colgando
de `main`:

```
git push --force origin historial-limpio:main
```

Después conviene borrar las cinco ramas `claude/*` viejas, que todavía apuntan
a los objetos originales.

**Cuidado si el force-push se hace:** el `.bat` del usuario, si su carpeta es
un **clon de git**, actualiza con `git pull --ff-only`. Contra un historial
reescrito eso falla, y el updater dice *"no se pudo... sigo con la versión que
tengo"* y **se queda en el código viejo para siempre sin que se note**. Él baja
el zip, así que no le afecta, pero verificalo con `arrancado_en` en
`/api/estado-sistema`. Si alguna vez pasa, la salida es borrar la carpeta y
bajar el zip de nuevo (la base vive afuera, no se pierde nada).

### Cómo se verificó, por si hay que rehacerlo

Se sacaron los 84 nombres que existieron en **cualquier** versión histórica de
`app/seed.py` y del JSON de la carta, y se buscó cada uno en los 2,7 MB de
todos los blobs + mensajes de commit + rutas del historial nuevo. Cero nombres
y cero ids. El único match es la palabra "reabriendo", que contiene "brie" por
casualidad.

Dos trampas que ese chequeo pescó y que hay que repetir si se rehace:

- **Comparar el árbol final contra el que se probó, archivo por archivo.** Un
  reemplazo `(?i)brie` convirtió "reabriendo" en "reachoclondo", y un `\bwrap\b`
  rompió `flex-wrap: wrap` dejándolo en `flex-producto: producto`. **Ninguna
  prueba detecta un CSS roto.**
- Los patrones de una sola palabra necesitan `\b` y lookbehind para el guión
  (`(?<!-)`) y para el valor CSS (`(?<!: )`).

Los archivos de reemplazo vivían en el scratchpad de esa sesión y **ya no
están**. No hace falta rehacerlos: el resultado está en `historial-limpio`. No
borres esa rama hasta que `main` esté cambiado.

### Lo que NO se puede borrar

Las páginas de los PR **#1 a #24** en GitHub siguen mostrando los diffs viejos
con la carta y los ids. Viven en `refs/pull/*`, del lado del servidor, y un
force-push no las toca. Las únicas dos salidas son borrar el repo público y
subir uno nuevo desde `historial-limpio` (barato: ya existe el clon privado), o
pedírselo a GitHub Support. **Está pendiente de decisión del dueño.**

## Cómo arranca una instalación nueva

`app/seed.py` viene **vacío** y los tres ids de sucursal **no tienen default**.
La pantalla ofrece dos pasos la primera vez: decir qué local sos (los campos
salen de `/api/config`) y después leer tu carta. Sin los ids la app no navega
a ningún menú: `plataformas.configurado` lo corta antes, porque entrar al menú
de otro local es peor que no arrancar.

`sembrar()` sólo crea productos si la base está vacía, así que esto no le
borra el catálogo a nadie que ya venía usando la app.

## Qué le pasa a una instalación que YA venía andando

Verificado simulando la actualización con una base con catálogo cargado y los
ajustes guardados: **el catálogo queda intacto y no aparece ninguna pantalla de
primer arranque**. La base vive en `%LOCALAPPDATA%\TodoSelector`, fuera de la
carpeta de la app, así que el autoupdate no la toca.

El único punto delicado es de dónde salen los ids de la sucursal. Antes estaban
en el código; ahora salen de la tabla `preferencias`:

- **Si alguna vez apretó Guardar en Ajustes**, están en su base y no cambia
  nada. Apretar Guardar manda las 13 opciones, incluidas las tres de Sucursal,
  con los valores que la pantalla tenía puestos — que en la versión vieja eran
  los del local. El dueño lo hizo el 2026-07-28.
- **Si nunca lo apretó**, `falta_sucursal` sale con las dos plataformas y la
  pantalla muestra un panel que dice *"Faltan los datos de tu sucursal — tu
  catálogo está intacto"*, con los tres campos ahí mismo. Se completa una vez y
  sigue todo igual. No se rompe nada y no hay que tocar la base.

**Cómo saber en cuál de los dos casos está**, sin adivinar: abrir
`http://127.0.0.1:8001/api/estado-sistema` y mirar `falta_sucursal`. Si es `[]`
está todo bien. Está cubierto por `probar_falta_solo_la_sucursal` dentro de
`probar_pantalla_carta.py`.

## Cómo se trabaja

- El usuario corre `iniciar_app.bat` en Windows. **Actualiza los archivos ANTES
  de levantar el server**: si deja la ventana abierta mientras se mergea, sigue
  con el código viejo. Verificar con `arrancado_en` en `/api/estado-sistema`.
- El auto-update baja de `main`: **hay que mergear a main** para que pueda
  probar. Se viene haciendo PR + merge en cada tanda. Él baja el **zip**, no
  usa `git pull`, así que un force-push a `main` no le rompe el updater.
- El entorno de desarrollo es Linux: **no se pueden correr el `.bat` ni el
  `.ps1`**. Sí se puede Playwright con
  `/opt/pw-browsers/chromium-1194/chrome-linux/chrome` (`executable_path=`).
- **Correr las pruebas antes de tocar nada.** Cubren casi todo sin navegador.
- Las pruebas con navegador levantan un server en un puerto fijo (8777, 8788,
  8799): **no correr dos a la vez** ni dejar una colgada, o la siguiente falla
  con `Address already in use` y hay que esperar el TIME_WAIT.

## Las pruebas — usalas, valen oro

```
py pruebas/probar_pedidosya.py        selectores y clicks, contra una réplica
py pruebas/probar_catalogo.py         vincular / separar / deshacer / migración
py pruebas/probar_estados.py          cómo se guarda el estado leído del portal
py pruebas/probar_cierre.py           apagar todo por plataforma + ajustes
py pruebas/probar_pantalla_carta.py   la app entera en modo simulado
py pruebas/probar_primer_arranque.py  sin catálogo y sin ajustes, como llega nueva
py pruebas/probar_rappi_sync.py       las dos tiendas de Rappi (Turbo y común)
```

`pruebas/portal_pedidosya.html` replica el DOM real. Acepta
`?popup=cerrable|pegado` y `?handler=hijo|host`.

La carta de ejemplo está armada para reproducir las trampas reales: prefijos
("Tarta de verdura" vs "Tarta de verdura chica"), tildes, variantes que NO son
el mismo plato, y nombres que no se parecen en nada entre portales. Si la
cambiás por algo fácil, las pruebas dejan de cubrir lo que importa.

---

## Lo que se construyó en las últimas sesiones

**Vista de prendidos** (PR #21). Tres vistas sobre la lista: por categoría,
prendidos primero (ordena, no esconde nada) y solo los prendidos (filtra). El
grupo del medio, *Sin confirmar*, **no se esconde nunca**: es lo que la app no
puede asegurar que esté apagado, o sea lo que puede estar vendiéndose.

**App genérica** (PR #22, #23, #24). Seed vacío, ids de sucursal desde
Ajustes, pantalla de primer arranque, y los datos del local fuera del código,
de la documentación, de los comentarios y de las pruebas. El #23 y el #24
fueron los restos que aparecieron al verificar contra la lista completa de
nombres: casi todos estaban en el TRASPASO viejo y en comentarios.

**Antes** (PR #19-20): apagar todo por plataforma, panel de Ajustes con 13
opciones, `/api/alertas`, y arreglos (el chip que se deseleccionaba solo, la
operación que se moría con la sesión caída, el doble click que duplicaba la
cola).

---

## Trampas que ya costaron caro — NO repetirlas

1. **PedidosYa, el toggle.** El `<input>` tiene `cdk-visually-hidden`.
   Clickearlo tarda 30.0s exactos y falla. Hay que clickear
   `span.mat-slide-toggle-bar`.
2. **Un click por JS sobre un custom element puede no hacer nada.** El listener
   vive en un hijo y los eventos suben, no bajan. Para eso está
   `clickear(..., profundo=True)`.
3. **Después de recargar hay que rehacer la preparación.** El popup de sonido
   vuelve en cada carga y su backdrop se come los clicks. `_confirmar()` llama
   a `asegurar_sesion()`.
4. **Los nombres se buscan con `exact=True`.** Una tilde y no encuentra nada.
5. **Cuidado con los prefijos.** "Tarta de verdura" vs "Tarta de verdura chica".
6. **`con` y `sin` NO son ruido** en el emparejador.
7. **Una pestaña por plataforma, con `asyncio.Lock`.**
8. **Falso "revivió" es caro**: reencola un apagado que *prende* el producto.
   Por eso hay una segunda lectura de confirmación antes de acusar.
9. **La pantalla no se puede cachear.** `index.html` va con `no-store`.
10. **El `.bat` necesita CRLF** (`.gitattributes` con `*.bat -text`).
11. **El identity map de SQLAlchemy resucita lo borrado.** En `deshacer()`,
    `expunge_all()`.
12. **Nada que el usuario haya elegido puede vivir en una variable local del
    repintado.** La lista se repinta cada 3 s y se lo lleva puesto, sin que se
    note. Pasó con los chips de plataforma. Ver `excluidas`, `filtro` y
    `vista` en `index.html`.
13. **No afirmar lo que no se está viendo.** Ver abajo.
14. **Los títulos de la pantalla van en MAYÚSCULA por CSS.** `inner_text()`
    respeta `text-transform`, así que una prueba que compara `"A confirmar"`
    falla y `has_text` (que ignora mayúsculas) pasa. Ya mordió dos veces.

## Datos del DOM confirmados

- **PedidosYa:** fila = `label.mat-slide-toggle-label`; estado = `aria-checked`
  del input; categorías = `wk-menu-list wk-menu-list-category-item` (el
  `wk-menu-list` importa). Popup: `Unavailable for today` /
  `Unavailable indefinitely` — **el portal está en inglés**. Prender NO abre
  popup.
- **Rappi:** toggle = `label[data-testid*="availability-switch-control"]`.
  Nombres = `alt` de `img[data-testid="catalog-item-image"]`. Estado = badge
  "Apagados" o `is_checked()`. Diálogos de apagado: radio "Sólo por hoy" →
  modal "¿Desactivar producto?" → botón "Sí, desactivar". Prender NO abre nada.
- **Rappi reescribe la URL** con los storeIds de todas las tiendas, así que
  `en_el_menu()` compara por partes y no el string entero.

---

## EL BUG MÁS CARO: el pedido de algo apagado

**2026-07-28.** El usuario apagó un producto, Todo-Selector lo mostró como
`apagado`, y **media hora después entró un pedido de PedidosYa con eso**. Es
el peor fallo posible de esta app.

**Mecanismo identificado y tapado:** si la lectura de la carta no encuentra un
producto, la app *no pisa* el estado que tenía (correcto: una lectura mala no
puede borrar lo que sabíamos), pero el `apagado` viejo quedaba **congelado** y
la pantalla lo seguía afirmando en presente. Ahora `_guardar_estados()`
devuelve `no_encontrados`, `/api/alertas` lo cruza con lo que la app da por
apagado, y sale un cartel rojo con el nombre exacto que estaba buscando.

**PERO la causa raíz NO está confirmada.** En el log del 28 los dos portales
dieron **`0 del catalogo no aparecieron`**, así que en ese momento no había
ningún producto invisible para la app. El camino que tapamos existe y era
real, pero puede no ser el que causó *ese* pedido.

Hipótesis que quedan abiertas, en orden:

1. **Era `apagado (afuera)` y no `apagado por hoy`.** La app **no sostiene**
   `APAGADO_AJENO` a propósito (`_guardar_estados`, `sostener`): si el portal
   lo revive, la ronda actualiza la pantalla pero no lo vuelve a apagar. Si el
   usuario lo apagó desde el portal y no desde la app, esto explica todo.
   **Cómo confirmarlo:** preguntarle si lo apagó desde Todo-Selector o desde
   PedidosYa, y qué decía el chip exactamente (`apagado hoy` vs
   `apagado (afuera)`).
2. **El "apagado por hoy" de PedidosYa venció.** `Unavailable for today` lo
   revive el portal solo. Si el apagado era de la noche anterior, a la mañana
   está prendido: la ronda lo detecta y lo reencola, pero hay una ventana.
3. **La ronda no corrió** (app recién arrancada, o la ventana del `.bat`
   cerrada).

**Lo más útil que puede hacer la próxima sesión:** que la reverificación quede
registrada en algún lado que el usuario pueda mirar después. Hoy si la ronda
detecta un revivido lo dice en el log de la consola y lo reencola, pero si el
usuario cerró la ventana no queda rastro. `/api/historial` ya guarda las
operaciones con su `detalle`; falta mostrarlo en pantalla (pendiente viejo).

---

## Rendimiento medido en el log del 2026-07-28

| | op#63 prender (PedidosYa) | op#64 prender (Rappi) |
|---|---|---|
| duración total | **30 s** | **18 s** |
| de eso, click fallado | 10 s | 8 s |

**El click normal sobre el toggle falla SIEMPRE y va por el fallback JS**, en
los dos portales. Son 8-10 segundos tirados por operación. Con "Apagar todo"
son ~26 productos por portal, o sea **~13 minutos** para PedidosYa, de los
cuales ~4 son puro timeout.

**Pista del log:**

```
click normal sobre toggle fallo (Locator.click: Timeout 10000ms exceeded.
Call log: - waiting for get_by_text("...", exact=True).first.locat...)
```

El timeout es **esperando que el locator resuelva**, no "element is covered by
another element" ni "not enabled". Eso apunta a que `get_by_text(...).first`
está agarrando un elemento que **no es visible** (PedidosYa deja en el DOM
elementos de categorías cerradas), y Playwright espera a que se vuelva
accionable hasta agotar el timeout. El click por JS después funciona porque no
mira visibilidad — pero eso significa que **puede estar clickeando el elemento
equivocado**, y eso es exactamente el tipo de cosa que produce un "apagué X y
se apagó Y".

**Cómo investigarlo sin adivinar:** con la app corriendo,
`/api/diagnostico?plataforma=pedidosya&nombre=<producto>` devuelve el HTML
crudo de la fila, y `/api/esqueleto?plataforma=pedidosya` el árbol del DOM. Lo
que hay que contestar es **cuántos elementos matchean `get_by_text(nombre,
exact=True)` y cuáles son visibles**. Si hay más de uno, `_fila()` tiene que
filtrar por visible antes del `.first`.

---

## Decisiones del usuario (no volver a preguntar)

- **Los platos del día se sacaron** (estorbaban). No reimplementarlos.
- El catálogo está en modo manual (`CATALOGO_MANUAL`): `seed.py` no pisa los
  alias, y además ya viene vacío.
- Los productos que existen en un solo portal no se cargan a mano: se agregan
  desde la pantalla Carta cuando hacen falta.
- La app opera sobre **las dos** tiendas de Rappi (2026-07-29). Turbo y común
  son independientes y con cartas distintas; la segunda es opcional y se
  prende con `rappi_comun_store_id` en Ajustes.
- **Nada de espejos automáticos entre plataformas.** Lo que se apaga es lo que
  el usuario eligió con los chips y los botones, ni más ni menos. Que apagar
  en Turbo apague en común sale de que sean el MISMO producto del catálogo
  (los dos chips vienen puestos), no de una regla que propague por atrás.
- **Lo dudoso lo decide el usuario, una vez, en la pantalla Carta**, y queda
  guardado. La app no empareja sola entre las dos tiendas de Rappi si no es
  prácticamente el mismo nombre.

## Próximos pasos

1. **Terminar la limpieza del historial**: el `push --force` de arriba, y
   después borrar las ramas `claude/*`. Es un comando y está todo verificado.
   Falta también que el dueño decida si quiere repo nuevo por lo de los PR.
2. **El click fallado del toggle** (arriba). Es el que más tiempo cuesta ahora
   que existe "Apagar todo", y el que más riesgo esconde.
3. **Mostrar el historial de operaciones en pantalla** (`/api/historial` ya lo
   devuelve). Es lo que falta para poder reconstruir qué pasó con un producto
   sin tener la ventana del `.bat` abierta. Ver la sección del bug más caro.
4. Terminar el `TODO-SELECTOR` de Rappi: HTML de la tarjeta y pantalla de
   sesión expirada.
5. ~~Apagar en varias tiendas de Rappi a la vez.~~ **HECHO (2026-07-29).** El
   usuario confirmó que en su local Turbo y común son tiendas independientes y
   **no comparten la carta**. La app opera sobre las dos: dos pestañas con dos
   `storeId` (no se itera la URL), la pantalla Carta lee y vincula las tres, y
   «Apagar todo» tiene los cinco destinos que pidió (cada una sola, ambos
   Rappi, las tres). Ver «Las dos tiendas de Rappi» en el README.

## Diagnóstico disponible (todo GET, no modifican nada)

```
/api/estado-sistema                          arrancado_en, sesiones, ultima_lectura,
                                             falta_sucursal, catalogo_vacio
/api/alertas                                 lo que da por apagado y no puede confirmar
/api/config                                  los ajustes y su valor actual
/api/catalogo                                qué nombre tiene cada producto en cada portal
/api/nombres?plataforma=                     la carta que muestra el portal
/api/carta[?releer=false]                    lee las dos y propone el cruce
/api/verificar-catalogo?plataforma=          qué nombres del catálogo no están
/api/diagnostico?plataforma=&nombre=         lee uno + HTML crudo de la fila
/api/buscar-texto?plataforma=&fragmento=     cómo está escrito realmente
/api/estructura?plataforma=                  dónde vive la navegación
/api/esqueleto?plataforma=                   árbol del DOM (tag/id/clases/texto)
/api/masivo/previo?accion=                   cuántos tocaría cada portal
```

`/api/esqueleto` es el que resuelve "no sé dónde está esto" sin depender del
idioma.

## Reglas del proyecto

Están en `CLAUDE.md` y son cortas: no cambiar el contrato de los 4 métodos de
`plataformas/base.py` (agregar sí), preferir selectores por texto o rol,
`exact=True` siempre, toda operación se confirma releyendo, probar en modo
simulado antes de tocar worker o API, nada elegido por el usuario vive en el
repintado, no afirmar lo que no se está viendo, y **ningún dato de un local
real en el repo**.

## Nota sobre términos de servicio

Rappi y PedidosYa prohíben el acceso automatizado. Esto automatiza lo que el
usuario ya hace a mano con su propio login, pero la cuenta es del local y el
riesgo existe.
