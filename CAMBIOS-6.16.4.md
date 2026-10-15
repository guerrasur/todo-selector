# v6.16.4 — Evitar reaplicar filtros y leer filas sin descripción

- Se elimina la aplicación forzada del filtro al final de cada chequeo de
  sesión: ir_al_menu ya comprueba la tienda de la pestaña compartida.
- Las filas se encuentran desde switch + Editar + nombre, con o sin
  descripción/imagen. Categorías y textos de descripción/tags no son nombres.
- Una lectura sin productos genera un error con diagnóstico; no se registra
  como una carta leída con cero productos.
- La lectura general espera el fin de la tanda Rappi para no alternar tiendas
  entre las operaciones encoladas. Los diagnósticos por tienda siguen disponibles.
- Se evita navegar al endpoint antiguo de Conectividad desde Portal Aliados.
  El estado general de tienda queda sin confirmar hasta adaptar esa pantalla.

Se conserva la recarga necesaria para confirmar un cambio de disponibilidad.
Las pruebas del adaptador usan un DOM lxml con filas con/sin descripción,
prefijos, duplicados y categoría. Se comprueban además caché de selección,
cola, cancelaciones y verificación en dos pasos. Falta validar el resultado
y los diálogos de apagado sobre el portal real.
