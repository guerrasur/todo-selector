# 6.16.7 — Rappi operativo con el nuevo menú

El diagnóstico real confirmó la lectura de 30 productos por tienda al
abrir todas las categorías. Esta versión incorpora esa preparación a las
lecturas normales, al arranque y a la relectura después de recargar.

- Reanuda la cola de Rappi y sus lecturas habituales.
- Despliega solo categorías cerradas y verifica tienda antes de cada clic.
- Tolera espacios exteriores en el nombre sin confundir productos parecidos.
- Usa el diálogo ligado al switch del producto mediante aria-controls.
- Selecciona Sólo por hoy (today) o No disponible indefinidamente
  (indefinitely), comprobando también el texto de la opción.
- Atiende la confirmación adicional conocida si aparece, dentro de su diálogo.
- Confirma el apagado leyendo el estado después de recargar; no da éxito
  por haber pulsado un botón. Nunca prende un apagado para cambiar duración.
- Conserva la pestaña compartida y las tandas Turbo antes de Común.

Actualizar y reiniciar. Se reanudarán las operaciones pendientes: no es otra
versión de diagnóstico. El primer uso del diálogo nuevo requiere verificar
el log real; enviar las primeras operaciones, incluyendo cualquier error.

Validación: pruebas locales de duración, diálogo asociado, selección ambigua,
etiqueta incompatible, cambio de tienda y estado que sigue prendido; lectura
con espacios y apertura en las lecturas; regresiones de cola, categorías,
selección, dropdowns y verificación manual. Sin ejecución contra una tienda
real desde el entorno de desarrollo.
