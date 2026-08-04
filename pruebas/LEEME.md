# Pruebas

Todas corren **sin tocar los portales** y sin tocar tu base: usan una carpeta
temporal y una réplica local del portal. Se pueden correr en cualquier máquina.

```
py pruebas/probar_pedidosya.py        selectores y clicks de PedidosYa
py pruebas/probar_rappi_menu.py       selectores y clicks del menu de Rappi
py pruebas/probar_catalogo.py         vincular / separar / sembrar
py pruebas/probar_estados.py          guardar el estado leído del portal
py pruebas/probar_cierre.py           apagar todo por plataforma + ajustes
py pruebas/probar_pantalla_carta.py   la pantalla entera, de punta a punta
py pruebas/probar_primer_arranque.py  cómo arranca una instalación nueva
py pruebas/probar_rappi_sync.py       las dos tiendas de Rappi (Turbo y Común)
py pruebas/probar_rappi_conectividad.py  el badge de tienda abierta/cerrada
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

Lo que prueba, además de que apagar y prender funcionen, es que el click
normal **entra** — sin pasar por el fallback JS.

**`probar_catalogo.py`** cubre el mapeo de nombres: que una base vieja se
corrija al arrancar, que vincular fusione y separar desarme, que el estado y
la cola de operaciones sobrevivan, y que `seed.py` deje de pisar los alias
cuando el catálogo pasa a manejarse desde la app.

**`probar_estados.py`** cubre lo delicado de leer el estado real: que una
operación en curso no la pise una lectura, que la app no se apropie de lo que
apagó el local por su cuenta (`apagado_ajeno`, que la ronda de reverificación
deja en paz), y que lo que el portal no mostró no borre lo que ya sabíamos —
pero que **quede avisado**, que es el bug del 2026-07-28: la pantalla decía
"apagado" y entró un pedido de eso.

También cubre el bug del 2026-08-03: la verificación de 2 minutos reencolaba
un apagado sobre algo que **el usuario acababa de prender**. Ahora corta si el
estado ya no es un apagado propio, y ni siquiera va a mirar el portal.

**`probar_cierre.py`** cubre el botón de "apagar todo" y los ajustes. Lo que
importa ahí es lo que **no** se encola: apagar la carta entera son ~30
operaciones por portal y cada una recarga la página, así que encolar de más es
la diferencia entre un minuto y veinte. Cubre también que apagar una plataforma
deje la otra intacta, que apretarlo dos veces no duplique la cola, y que los
ajustes validen antes de guardar (una tanda con un valor malo no guarda ninguno).
Desde el 2026-08-04 cubre además desactivar una tienda: que pedir *indefinido*
sí reencole lo que estaba apagado **por hoy** (ese vuelve solo mañana), y que
una tienda **en pausa** se pueda apagar pero no prender — ni con «Prender
todo», ni de a un producto, ni asomándose en el aviso de la tienda hermana.

Desde el 2026-08-04 cubre también el reintento automático de lo que falló
(`probar_estados.py`): que vuelva solo a la cola pasados los minutos, pero
**no** si en el medio se pidió otra cosa para ese producto, si ya quedó como
se pedía, si el producto está en pausa, o si ya agotó el tope — y que la misma
fallida no se evalúe dos veces, que sería un reintento por minuto para siempre.

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
