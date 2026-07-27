# Pruebas

Todas corren **sin tocar los portales** y sin tocar tu base: usan una carpeta
temporal y una réplica local del portal. Se pueden correr en cualquier máquina.

```
py pruebas/probar_pedidosya.py        selectores y clicks de PedidosYa
py pruebas/probar_catalogo.py         vincular / separar / sembrar
py pruebas/probar_pantalla_carta.py   la pantalla Carta, de punta a punta
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

**`probar_pantalla_carta.py`** levanta la app entera en modo simulado y la
maneja con Playwright como lo haría una persona. En modo simulado `/api/carta`
devuelve `carta_2026-07-27.json`, que es la lectura **real** de los dos
portales de ese día: sirve para probar la pantalla sin estar en el local.
