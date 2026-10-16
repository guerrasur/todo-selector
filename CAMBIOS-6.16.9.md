# 6.16.9 — Confirmación final al desactivar en Rappi

- Después de elegir «Sólo por hoy» o «No disponible indefinidamente», espera
  el pop-up «¿Desactivar producto?» y pulsa «Sí, desactivar» dentro de él.
- Amplía la espera de 2 a 15 segundos y exige la confirmación: si falta,
  informa el error en lugar de seguir como si el paso fuera opcional.
- Comprueba la tienda antes de confirmar y espera que se cierre el pop-up
  antes de recargar y verificar que el producto quedó apagado.

Pruebas locales con dobles del portal: ambas duraciones con confirmación
demorada más de 2 segundos, confirmación
ausente o ambigua, cambio de tienda, modal que no cierra y relectura que
todavía muestra el producto prendido. Pendiente validar en el portal real.
