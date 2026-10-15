# 6.16.8 — Evitar cambios de tienda entre operaciones

- El estado general de la tienda Rappi, todavía sin adaptar, devuelve
  desconocido sin preparar ni navegar la carta.
- Las lecturas esperan durante la tanda de Rappi, también cuando se piden
  explícitamente o la última operación espera el bloqueo de la pestaña.
- Las operaciones conservan su turno y las guardas de tienda, última intención
  y verificación manual. PedidosYa sigue trabajando normalmente.
- Si un nombre remoto no está en la carta, el error indica que se revise el
  vínculo en Carta, en lugar de mostrar solo «no se pudo confirmar el cambio».

No modifica vínculos automáticamente ni inventa duración indefinida de un
producto ya apagado. Los OK por «ya estaba apagado» son verificaciones de
estado: no prueban un apagado nuevo.

Pruebas locales: preparación durante tanda, operación esperando lock y
limpieza del turno, estado de tienda sin navegación, nombre exacto ausente,
regresiones de cola y verificación, y apagado del nuevo portal.
