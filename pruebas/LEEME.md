# Pruebas

Todas corren **sin tocar los portales** y sin tocar tu base: usan una carpeta
temporal y una réplica local del portal. Se pueden correr en cualquier máquina.

```
py pruebas/probar_pedidosya.py        selectores y clicks de PedidosYa
py pruebas/probar_catalogo.py         vincular / separar / sembrar
py pruebas/probar_estados.py          guardar el estado leído del portal
py pruebas/probar_cierre.py           apagar todo por plataforma + ajustes
py pruebas/probar_pantalla_carta.py   la pantalla entera, de punta a punta
py pruebas/probar_primer_arranque.py  cómo arranca una instalación nueva
```

Las dos que usan navegador necesitan Playwright instalado
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

**`probar_cierre.py`** cubre el botón de "apagar todo" y los ajustes. Lo que
importa ahí es lo que **no** se encola: apagar la carta entera son ~30
operaciones por portal y cada una recarga la página, así que encolar de más es
la diferencia entre un minuto y veinte. Cubre también que apagar una plataforma
deje la otra intacta, que apretarlo dos veces no duplique la cola, y que los
ajustes validen antes de guardar (una tanda con un valor malo no guarda ninguno).

**`probar_pantalla_carta.py`** levanta la app entera en modo simulado y la
maneja con Playwright como lo haría una persona. En modo simulado `/api/carta`
devuelve `carta_2026-07-27.json`, que es la lectura **real** de los dos
portales de ese día: sirve para probar la pantalla sin estar en el local.

Además del recorrido de la Carta cubre el panel de **Apagar todo**, el de
**Ajustes**, las **vistas de prendidos** (que "prendidos primero" no esconda
nada, que "solo los prendidos" sí, que ninguna de las dos esconda un apagado
que la app no puede confirmar, y que la vista elegida sobreviva al repintado
y a recargar), y una regresión que costó caro: el chip de plataforma se
deseleccionaba solo. La lista se repinta cada pocos segundos, y la selección
vivía en una variable local del repintado; si tardabas más que el refresco en
apretar el botón, la acción salía a los dos portales sin decir nada.

**`probar_primer_arranque.py`** levanta la app **sin catálogo y sin ajustes**,
que es exactamente como le llega a alguien que la baja por primera vez. Cubre
lo que se pidió el 2026-07-28: que un usuario nuevo **no** se encuentre con la
carta ni con la sucursal de otro. Comprueba que no haya ni un producto cargado,
que la pantalla pida los dos pasos en orden, que "Leer mi carta" esté bloqueado
hasta decir qué local sos, que no se guarde media sucursal, y que el panel se
vaya cuando ya no hace falta.

## La carta de ejemplo

`app/seed.py` viene **vacío** a propósito, así que las pruebas traen su propia
carta inventada: `catalogo_ejemplo.py` (el catálogo) y `carta_ejemplo.json` (lo
que devuelve `/api/carta` en modo simulado). Los dos van de la mano: si tocás
uno, tocá el otro.

No es una lista cualquiera. Reproduce las trampas que ya costaron caro, porque
un ejemplo fácil deja de cubrirlas:

- **prefijos** — "Tarta de verdura" es prefijo de "Tarta de verdura chica";
- **tildes** — el canónico "Budín de pan" y el nombre sin tilde de PedidosYa;
- **nombres que no se parecen en nada entre portales** — "Agua chica" contra
  "Manantial sin gas 500 ml";
- **variantes que NO son el mismo plato** — "chica", "individual" y "porción"
  puntúan altísimo entre sí;
- **productos que existen en un solo portal**, en los dos sentidos.

Los ids de sucursal de `catalogo_ejemplo.SUCURSAL` también son de mentira: lo
único que importa es que existan, para que las pruebas no se queden en la
pantalla de primer arranque.
