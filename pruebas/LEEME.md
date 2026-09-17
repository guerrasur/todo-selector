# Pruebas

Todas corren **sin tocar los portales** y sin tocar tu base: usan una carpeta
temporal y una réplica local del portal. Se pueden correr en cualquier máquina.

```
py pruebas/probar_pedidosya.py        selectores y clicks de PedidosYa
py pruebas/probar_rappi_menu.py       selectores y clicks del menu de Rappi
py pruebas/probar_catalogo.py         vincular / separar / sembrar
py pruebas/probar_estados.py          guardar el estado leído del portal
py pruebas/probar_verificacion.py     la verificación en dos pasos de Rappi
py pruebas/probar_cierre.py           apagar todo por plataforma + ajustes
py pruebas/probar_pantalla_carta.py   la pantalla entera, de punta a punta
py pruebas/probar_primer_arranque.py  cómo arranca una instalación nueva
py pruebas/probar_rappi_sync.py       las dos tiendas de Rappi (Turbo y Común)
py pruebas/probar_rappi_conectividad.py  el badge de tienda abierta/cerrada
py pruebas/probar_backup.py           la copia de seguridad de la base
```

Las que usan navegador necesitan Playwright instalado
(`py -m playwright install chromium`).

## Qué cubre cada una

**`probar_pedidosya.py`** levanta `portal_pedidosya.html`, que replica el DOM
real del portal (los `<mat-slide-toggle>` con el input `cdk-visually-hidden`,
las categorías `<wk-menu-list-category-item>`, el popup de sonido y su
backdrop) y corre la clase `PedidosYa` de verdad contra él. Dos escenarios:

- **popup cerrable**, que es lo que pasa en producción;
- **backdrop pegado**, donde *todos* los clicks tienen que ir por el fallback
  JS. Este es el que fallaba antes del arreglo del 2026-07-27.

El HTML acepta parámetros para cambiar la dificultad: `?popup=cerrable|pegado`
y `?handler=hijo|host` (dónde vive el listener de la categoría).

Desde el 2026-08-14 cubre además **la categoría de cada producto**: que
`categorias_de_productos()` diga en cuál está cada uno saliendo del mismo
recorrido que ya hace para leer la carta (no una segunda vuelta, que son
minutos), que las traiga de las tres categorías, y que sin haber leído
todavía no afirme ninguna — `{}` es «no sé», no «no tienen» (regla 8).

**`probar_rappi_menu.py`** levanta `portal_rappi_menu.html` y corre la clase
`Rappi` de verdad contra él. Reproduce las cuatro trampas que el log del
2026-08-03 dejó ver:

- la franja `menu-categories-hoverable-gap`, un overlay invisible que se comía
  **todos** los clicks sobre los toggles (`?gap=no` la saca, para comparar);
- el header de categoría pegajoso;
- un «Sólo por hoy» invisible en el DOM además del real, que el modal monta
  con retardo: ahí es donde el `.first` de antes clickeaba un fantasma;
- dos nombres ambiguos, uno repetido dentro de **una** tarjeta (inofensivo) y
  otro que existe en **dos** tarjetas (ahí no se toca nada y se tira
  `NombreAmbiguo`);
- y con `?dialogo=portal`, el diálogo de verdad: un portal de `floating-ui`
  con las opciones en `menu-item-availability-switch-option-N` y el texto que
  **no** es el nuestro carácter por carácter («Solo por hoy», sin tilde). Ahí
  se prueba que la opción se encuentre igual comparando sin tildes, que no se
  elija nunca por posición (la 3ª es "Personalizar", que no apaga nada), y que
  un diálogo que no se pudo resolver no quede abierto tapando el intento
  siguiente.

Desde el 2026-08-14 cubre también **de qué categoría es cada producto**, por
los dos caminos que se ven en el DOM del portal y que todavía no están
confirmados como par (ver el TODO-SELECTOR en `rappi.py`): con
`?categorias=dos` la carta viene partida en dos grupos, cada uno con su
`<li data-testid="menu-category">` y su header adentro —con una sola
categoría cualquier cosa acierta—, y sin ese parámetro queda el header
pegajoso suelto arriba de las tarjetas. Y que sin ningún título no se
invente ninguna categoría.

Desde el 2026-08-20, con `?carta=plegada`, cubre además **una carta que no
es una carta**: las tres categorías llegan plegadas, así que no hay ni un
producto renderizado, pero sí están los toggles de **categoría**
(`menu-category-N-availability-switch-control`), que terminan igual que los
de producto. Antes eso pasaba por «el menú cargó» y los 3 intentos se
gastaban buscando un producto que no existía en el DOM. Se prueba que
`asegurar_sesion()` conteste que no, y que `huella_de_pantalla()` deje en el
log qué se vio — incluida la pestaña cerrada, donde tiene que contestar en
vez de tirar.

Y con `?tapa=ancestro`, las tres trampas del 2026-08-05, que son las que
explicaban el «Rappi Turbo no apaga y se queda trabada»:

- lo que tapa el toggle es un **ancestro** suyo (un `::after` del
  `<ul data-testid="menu-categories">`, más otro de un contenedor que **no**
  está en `SELECTORES_ESTORBO`): el primero lo resuelve
  `neutralizar_estorbos()` y el segundo el peldaño de *destapar* de
  `clickear()`, que es el que sigue sirviendo cuando el portal cambia el DOM
  otra vez;
- el popup se abre **solo con `pointerdown`** sobre la perilla de adentro del
  `<label>`: un `.click()` disparado en el label lo prende pero no abre nada;
- el `for="switch-hidden-input"` del label, con ese `id` repetido en toda la
  carta — activar el label por la vía nativa apagaría el **primer** producto
  del documento, no el que pediste.

Lo que prueba, además de que apagar y prender funcionen, es que el click
normal **entra** — sin pasar por el fallback JS — y que los `pointer-events`
que se tocaron para destapar quedan restaurados.

**`probar_catalogo.py`** cubre el mapeo de nombres: que una base vieja se
corrija al arrancar, que vincular fusione y separar desarme, que el estado y
la cola de operaciones sobrevivan, y que `seed.py` deje de pisar los alias
cuando el catálogo pasa a manejarse desde la app.

Desde el 2026-08-14 cubre además **empezar la carta de cero**
(`catalogo.reiniciar`), que es lo que hay que apretar cuando el portal
renombró media carta y todos los alias quedaron apuntando a texto que ya no
existe. Lo que se prueba no es el borrado —eso es una línea— sino lo que
**no** se lleva puesto: que los ajustes de sucursal sobrevivan (viven en la
misma tabla `preferencias` que las marcas del catálogo), que la cola quede
CANCELADA y no en ERROR, que el historial ya terminado no se toque, que
reiniciar la app no lo resucite, y que «Deshacer» devuelva el catálogo entero
con los MISMOS ids (si no, las operaciones del historial quedarían colgadas).

**`probar_estados.py`** cubre lo delicado de leer el estado real: que una
operación en curso no la pise una lectura, que la app no se apropie de lo que
apagó el local por su cuenta (`apagado_ajeno`, que la ronda de reverificación
deja en paz), y que lo que el portal no mostró no borre lo que ya sabíamos —
pero que **quede avisado**, que es el bug del 2026-07-28: la pantalla decía
"apagado" y entró un pedido de eso.

También cubre el bug del 2026-08-03: la verificación de 2 minutos reencolaba
un apagado sobre algo que **el usuario acababa de prender**. Ahora corta si el
estado ya no es un apagado propio, y ni siquiera va a mirar el portal.

Desde el 2026-08-14 cubre además la **categoría leída del portal**: que con
un solo portal que la sepa mande esa, que cuando PedidosYa la sabe mande la
de PedidosYa (`carta.ORDEN`) sin perder la de Rappi, que una lectura sin
categorías no borre las que había, y que la que escribís vos no la pise
nunca la lectura — pero que la del portal se siga actualizando igual, porque
son dos cosas distintas.

**`probar_verificacion.py`** cubre el modo *«esta pestaña es mía»*: cuando
Rappi pide el código de verificación en dos pasos, el usuario tiene que
quedarse varios minutos en esa pantalla y **cualquier recarga lo invalida**.
Lo que se prueba no es que algo devuelva `False` sino que **nadie toque la
pestaña**: la pestaña de mentira anota cada recarga, navegación y cierre, y la
prueba mira ese registro.

Cubre el corte de `_preparar` —que va antes del reload **y antes de
`asegurar_sesion()`**, que navega igual aunque la pestaña esté fresca—, que la
cola de esa plataforma espere sin gastar intentos ni terminar en ERROR, que la
espera **no venza** (a diferencia de la sesión caída, que reintenta a los
60 s), que la otra plataforma siga trabajando, que congelar Rappi Turbo
congele también Rappi Común, que guardar Ajustes no le cierre la pestaña, y
que el **botón manual funcione aunque la detección automática no reconozca la
pantalla** — que es el caso para el que está hecho, porque los textos de esa
pantalla todavía no se confirmaron contra el portal real.

Desde el 2026-08-13 cubre además el otro «no es lo que parece» del mismo
archivo: **un menú que no carga no es una sesión caída**. `asegurar_sesion()`
devuelve `False` por dos motivos que se arreglan distinto —el campo de
contraseña, o el menú que no apareció en 15 s— y los dos salían como
«logueate de nuevo». Con las dos tiendas de Rappi quedó a la vista: entran
con la **misma cuenta**, así que «rappi: OK» y «rappi_comun: REQUIERE LOGIN»
en el mismo arranque no puede ser el login. Se prueba que sin campo de
contraseña el mensaje no mande a loguearse, que una sesión caída de verdad
siga diciendo lo de siempre, que si no se pudo ni mirar la pestaña no se
afirme ninguna de las dos (regla 8), que la pantalla reciba cada caso en su
propio aviso, y que el motivo **no** le cambie nada a la cola (sigue mirando
`sesion_ok`).

La pantalla está cubierta aparte, en `probar_pantalla_carta.py`: que el cartel
dé los pasos concretos, que diga que lo encolado está esperando y no perdido,
y que una plataforma congelada **no** salga además como sesión caída (dos
carteles que se contradicen).

**`probar_cierre.py`** cubre el botón de "apagar todo" y los ajustes. Lo que
importa ahí es lo que **no** se encola: apagar la carta entera son ~30
operaciones por portal y cada una recarga la página, así que encolar de más es
la diferencia entre un minuto y veinte. Cubre también que apagar una plataforma
deje la otra intacta, que apretarlo dos veces no duplique la cola, y que los
ajustes validen antes de guardar (una tanda con un valor malo no guarda ninguno).
Desde el 2026-08-04 cubre además desactivar una tienda: que pedir *indefinido*
sí reencole lo que estaba apagado **por hoy** (ese vuelve solo mañana), y la
regla de la tienda **en pausa** — se toca solo cuando la nombrás (el botón de
su propia fila la apaga; un combo que no la nombra la deja afuera) y prender
no se toca nunca, ni asomándose en el aviso de la tienda hermana.

Desde el 2026-08-04 cubre también el reintento automático de lo que falló
(`probar_estados.py`): que vuelva solo a la cola pasados los minutos, pero
**no** si en el medio se pidió otra cosa para ese producto, si ya quedó como
se pedía, si el producto está en pausa, o si ya agotó el tope — y que la misma
fallida no se evalúe dos veces, que sería un reintento por minuto para siempre.

Desde el 2026-08-05 cubre además la **cola**: que se pueda ver entera y en
orden, que cancelar una saque esa y no las demás, que la que **ya está
corriendo** quede cancelada sin volver a `PENDIENTE` (el intento en vuelo
termina, pero no hay intento 2) y sin que el reintento automático la traiga de
vuelta, que un producto cancelado quede en `DESCONOCIDO` y no en un estado
inventado, que una operación que falla **deje pasar a la de atrás** en vez de
quedarse con el turno, y que una `EN_CURSO` de una corrida anterior vuelva a
la cola al arrancar en vez de quedar colgada para siempre.

**`probar_pantalla_carta.py`** levanta la app entera en modo simulado y la
maneja con Playwright como lo haría una persona. En modo simulado `/api/carta`
lee las cartas inventadas de `carta_ejemplo.json` y **las cruza con el
emparejador de verdad**, así que la pantalla simulada muestra exactamente lo
que mostraría contra los portales. (Antes ese archivo guardaba el resultado ya
cruzado, escrito a mano, y se había despegado de lo que el código produce.)

Además del recorrido de la Carta cubre el panel de **Apagar todo**, el de
**Ajustes**, las **vistas de prendidos** (que "prendidos primero" no esconda
nada, que "solo los prendidos" sí, que ninguna de las dos esconda un apagado
que la app no puede confirmar, y que la vista elegida sobreviva al repintado
y a recargar), y una regresión que costó caro: el chip de plataforma se
deseleccionaba solo. La lista se repinta cada pocos segundos, y la selección
vivía en una variable local del repintado; si tardabas más que el refresco en
apretar el botón, la acción salía a los dos portales sin decir nada.

Desde el 2026-08-14 cubre las **categorías en la pantalla**: que la fila
muestre la de los dos portales («Empanadas · Para picar»), que el título diga
cuál es de cuál, que la lista se agrupe con la de PedidosYa, que la que
escribís a mano sea la que se ve, y que dejándola vacía vuelvan las de los
portales.

Desde el 2026-08-14 cubre el **orden de las categorías**: que el grupo
arrastrado quede donde lo soltaste, que se pueda mandar uno al final
(soltando en la mitad de abajo del último, que es el caso sin el cual solo se
podría subir a los demás), que el repintado automático **no** lo devuelva a
donde estaba (regla 7), que sobreviva a recargar porque vive en la base, y
que un click sin arrastrar no mueva nada. Se maneja con el mouse de verdad
(mousedown/mousemove/mouseup) y no con `drag_to`: la pantalla no usa el
drag-and-drop de HTML5, justamente porque contra esta página Chromium no lo
dispara.

Y el botón rojo del final de **Ajustes**
(«Desvincular las cartas y empezar de cero»), de punta a punta y en ese orden:
que el primer click **no** borre sino que abra la confirmación con los números
a la vista, que «Mejor no» salga sin consecuencias, que después de borrar la
app quede en la pantalla Carta leyendo los portales (que es para lo que
apretaste) con todo para elegir de nuevo, y que los ajustes de sucursal sigan
ahí. Corre al final de todo por lo obvio: borra el catálogo que usan las demás.

**`probar_rappi_sync.py`** cubre la segunda tienda de Rappi. Rappi Turbo y
Rappi Común son dos tiendas del mismo local que **no comparten la carta**:
apagar en una no apaga en la otra, un plato puede estar en una y no en la
otra, y puede llamarse distinto en cada una. Cubre que el emparejador cruce
tres cartas sin cambiar lo que hacía con dos, que **entre dos tiendas del
mismo portal se exija más** para emparejar solo (la trampa: "Empanada de
carne chica" puntúa 0.91 contra "Empanada de carne" y es otro plato), que el
catálogo pueda representar dos o tres botones, que fusionar productos no
borre en silencio la tercera tienda, que al apagar mande **la selección
explícita** (nada de espejos por atrás), que lo no vinculado se saltee en vez
de apagar cualquier cosa, y que quede avisado lo que terminó apagado en una
tienda y prendido en la otra.

**`probar_rappi_conectividad.py`** cubre el badge 🟢/🔴 del header (si la
TIENDA entera está tomando pedidos). Corre la clase `Rappi` de verdad contra
`portal_rappi_conectividad.html`, que replica el DOM real de Administración →
Conectividad: **no es una tabla**, es un div de styled-components con clases
generadas y un `data-testid` genérico que comparte todo texto del portal. Esa
era la trampa: el código buscaba `<td>Estado</td>`, encontraba cero celdas
siempre y las dos tiendas de Rappi quedaban en «sin datos» sin decir por qué
(2026-07-30). Cubre que lea el estado del div, que **reintente** mientras el
SPA todavía no lo pintó, que con dos tiendas y ningún nombre cargado devuelva
"no sé" en vez de adivinar cuál sos, que con el nombre cargado desempate por
la tarjeta **más cercana** (subiendo lo suficiente, el contenedor común
contiene los dos nombres y las dos daban positivo), que un estado desconocido
no se invente, y que **nunca** haya un "sin datos" mudo: si no se pudo
confirmar, hay motivo.

**`probar_primer_arranque.py`** levanta la app **sin catálogo y sin ajustes**,
que es exactamente como le llega a alguien que la baja por primera vez. Cubre
lo que se pidió el 2026-07-28: que un usuario nuevo **no** se encuentre con la
carta ni con la sucursal de otro. Comprueba que no haya ni un producto cargado,
que la pantalla pida los dos pasos en orden, que "Leer mi carta" esté bloqueado
hasta decir qué local sos, que no se guarde media sucursal, y que el panel se
vaya cuando ya no hace falta.

**`probar_backup.py`** cubre la copia de seguridad diaria de la base
(`app/backup.py`), que corre sola al arrancar y cada 3 horas. Lo que importa
no es que copie sino que la copia **sirva el día que haga falta**: se
comprueba que el archivo abra como base SQLite y tenga las tablas de la app,
no que exista y pese algo. Cubre que el del día no se rehaga porque sí, que
sí se rehaga cuando quedó más viejo que el umbral (envejeciendo el archivo
con `os.utime`, sin tocar el reloj), que la poda deje exactamente los 30 más
nuevos y no un rango al azar, y que los `.tmp` de una corrida que se cortó en
el medio se limpien y no queden haciéndose pasar por un backup. También que
con la base todavía inexistente devuelva `None` en vez de dejar un archivo
vacío. Como las demás, usa una carpeta temporal: no lee ni escribe tu base
real.

## La carta de ejemplo

`app/seed.py` viene **vacío** a propósito, así que las pruebas traen su propia
carta inventada: `catalogo_ejemplo.py` (el catálogo) y `carta_ejemplo.json`
(lo que "leen" los portales en modo simulado). Los dos van de la mano: si
tocás uno, tocá el otro. **Ojo con `carta_ejemplo.json`**: los números que
afirma `probar_pantalla_carta.py` ("A confirmar — 2", "Solo en Rappi — 7")
salen de correr el emparejador sobre esas listas, así que cambiar un nombre
los cambia.

No es una lista cualquiera. Reproduce las trampas que ya costaron caro, porque
un ejemplo fácil deja de cubrirlas:

- **prefijos** — "Tarta de verdura" es prefijo de "Tarta de verdura chica";
- **tildes** — el canónico "Budín de pan" y el nombre sin tilde de PedidosYa;
- **nombres que no se parecen en nada entre portales** — "Agua chica" contra
  "Manantial sin gas 500 ml";
- **variantes que NO son el mismo plato** — "chica", "individual" y "porción"
  puntúan altísimo entre sí;
- **productos que existen en un solo portal**, en los dos sentidos;
- **las dos tiendas de Rappi con cartas distintas** — platos que están en una
  y no en la otra, y una "Empanada de carne chica" que es prefijo de la
  "Empanada de carne" de las otras dos y NO es el mismo plato.

Los ids de sucursal de `catalogo_ejemplo.SUCURSAL` también son de mentira: lo
único que importa es que existan, para que las pruebas no se queden en la
pantalla de primer arranque.

## Regresiones v6.9

- `python pruebas/probar_regresiones_69.py`: 17 casos con SQLite temporal,
  adaptadores falsos y llamadas reales al worker/API. Incluye reintentos heredados,
  cambios de orden mientras se espera al navegador, cancelación, lecturas nulas,
  confirmaciones positivas y rechazo seguro de duración no confirmada.
- `node pruebas/probar_accion_ui.js`: 6 casos que ejecutan la función `accion`
  extraída del HTML con respuestas controladas: error HTTP, red, destinos
  omitidos, doble click, éxito y fallo de refresco. No necesita navegador.
  Node es solo para desarrollo; no es una dependencia nueva de la app.

Para esta entrega pasaron las seis suites sin navegador: catálogo, estados,
verificación, cierre, Rappi sync y backup. También se comprobó por HTTP local
el arranque simulado, versión 6.9, HTML, encolado, rechazo 404 y cancelación.
No se validaron portales reales ni interfaz visual: Chromium no pudo descargarse
en el entorno de revisión. No interpretar las pruebas aisladas como validación
de los selectores actuales de Rappi/PedidosYa.

## Duplicados v6.10

- `python pruebas/probar_duplicados.py`: 15 casos. Copias exactas, variantes,
  diferencias entre tiendas, conflictos, cola viva, firma vencida, backup,
  historial, lookup de archivados, deshacer y fusión sin nuevos restos.
- `node pruebas/probar_duplicados_ui.js`: vista previa sin mutación, nombres
  como texto seguro, envío explícito de firma, rechazo por cambios y conflictos.
- Backup SQLite real comprobado con la transacción de limpieza abierta.
- Suites de catálogo, estados, verificación, cierre, Rappi sync, backup y las
  17 regresiones de 6.9 aprobadas. No se validó visualmente en Chromium ni con
  sesiones reales. La limpieza se prueba con catálogos temporales inventados.
