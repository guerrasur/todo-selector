# Todo-Selector 6.11 — Precios beta

## Función

Actualizar carta → Precios (beta). Solo Rappi Turbo y Rappi Común configurados.
Selección explícita de tiendas, aumentos en $ o %, alcance total o por
productos, edición individual por tienda, búsqueda y redondeo opcional.

Los planes se calculan con Decimal del lado del servidor, usando una lectura
que vence a los 30 minutos. La vista previa fija precios absolutos: un doble
click o un fallo de conexión no aplica dos veces el porcentaje. Se comprueban
marca, tienda, nombre exacto, id del producto y precio de origen antes de
guardar. Las tiendas y lecturas incompletas se rechazan para el alcance total.

El adaptador usa lápiz → editor → Precio → Guardar, y relee una página
recargada antes de declarar confirmado. No modifica disponibilidad, nombre,
descripción ni personalizaciones. Los selectores nuevos del lápiz y campos
están identificados como TODO-SELECTOR: las capturas aportan evidencia visual,
pero falta validación del HTML real y una prueba en vivo.

## Ejecución y recuperación

Un único lote de precios a la vez. Usa el mismo bloqueo por pestaña y
preparación del worker; los controles de verificación manual siguen aplicando.
Los cambios se verifican sin volver a guardar. Los fallos no se reintentan
automáticamente. Cancelar afecta a los pendientes, dejando terminar el actual.

Los resultados están en el directorio de datos local, subcarpeta `precios`,
con escritura atómica antes y después de cada intento. Reiniciar muestra los
intentos interrumpidos como sin confirmar y no los reejecuta. La pantalla de
resultados anteriores conserva el precio anterior/nuevo y el detalle por fila.
El deshacer del catálogo no revierte precios de los portales.

## Pruebas

- `python pruebas/probar_precios.py`: importes, aumentos, selección, precios
  individuales, límites, exclusión de PedidosYa, idempotencia, conflictos,
  cancelación, bloqueo de pestañas y resultados persistidos.
- `python pruebas/probar_rappi_precios.py`: adaptador real contra réplica local,
  guardado lento/fallido, controles sin label, campos flotantes, categorías
  plegadas, productos sin foto y rechazo de identidades ambiguas.
- `python pruebas/probar_precios_ui.py`: pantalla y API reales en simulación,
  edición, vista previa, ejecución, navegación y exclusión de PedidosYa.

Para actualizar, cerrar y volver a abrir `iniciar_app.bat`: el actualizador
existente descarga main. No hace falta borrar la base ni configurar otra vez.
