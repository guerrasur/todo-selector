# StockSwitch — contexto para Claude Code

App local que apaga/prende productos en PedidosYa y Rappi desde una sola
pantalla. Reemplaza el trabajo manual de entrar a cada portal.

## Estado actual

El esqueleto está completo y probado en modo simulado. **Faltan los selectores
reales de las dos plataformas.**

## Tu tarea

Completar los `TODO-SELECTOR` en `plataformas/pedidosya.py` y
`plataformas/rappi.py`, probando en vivo con Chrome abierto en los portales.

El checklist completo está en el README, sección "TAREAS PENDIENTES".

## Reglas importantes

1. **No cambies el contrato de `plataformas/base.py`.** El worker depende de
   esos 4 métodos. Si necesitás algo más, agregalo sin romper los existentes.

2. **Preferí selectores por texto visible o rol** antes que clases CSS
   generadas. Estos portales cambian de UI seguido.

3. **Cuidado con nombres que son prefijo de otros.** "Wrap caesar" vs
   "Wrap caesar con batatas" — usar `exact=True` o el script apaga el
   equivocado. Esto ya mordió una vez.

4. **Toda operación se confirma releyendo.** Los métodos `apagar()` y
   `prender()` devuelven True solo si el cambio se verificó recargando la
   página. No confiar en que el click alcanzó — PedidosYa a veces no guarda.

5. **Probá con modo simulado primero** (`STOCKSWITCH_SIMULADO=1`) si tocás
   worker o API, para no depender del navegador.

## Cómo probar

```
py run.py
```

Abre en `localhost:8001`. La primera vez hay que loguearse a mano en las dos
pestañas del navegador que abre la app.

## Arquitectura en una línea

UI encola una `Operacion` → worker la toma → prepara la pestaña (refresca +
verifica login) → llama al método de la plataforma → confirma releyendo →
programa una reverificación a los 2 minutos.
