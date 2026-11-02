# Todo-Selector 6.9

Base: main, commit `1d31a1a588b1275192ce23cbff50171dbb187b54` (6.8).
Fecha: 2026-09-17.

## Qué cambia

1. Una orden individual nueva cancela los reintentos pendientes anteriores del
   mismo producto y portal. Si el intento anterior ya está ejecutándose, termina
   sin repetirse ni programar una reverificación que compita con la nueva orden.
   También se descartan reintentos viejos guardados por versiones anteriores.
2. Las reverificaciones comprueban el id de la última orden, el tipo de apagado,
   la pausa del producto/tienda y el nombre remoto. Se comprueban de nuevo después
   de esperar al navegador. Un nuevo pedido tiene prioridad.
3. Una lectura nula no renueva la fecha de confirmación. Si la primera lectura
   dice disponible y la segunda no encuentra el producto, tampoco se reencola.
4. Cancelar un intento que acaba fallando deja «sin leer», o muestra la nueva
   acción pendiente si existe. Ya no queda «apagando…» sin operación viva.
5. Los botones individuales muestran errores HTTP, problemas de conexión y
   plataformas omitidas; distinguen un fallo al enviar de un fallo al refrescar.
6. Los adaptadores ya no declaran éxito de un apagado indefinido basándose solo
   en que el producto estaba apagado. La operación queda en error explícito y no
   se reintenta automáticamente. No se reactiva el producto para intentar cambiar
   la duración. Ver la limitación de abajo.

## Límite que sigue pendiente

La conversión automática de «apagado por hoy» a «indefinido» sobre un producto
ya apagado requiere confirmar en el portal real cómo se edita su duración sin
volver a habilitar ventas. En esta versión hay que hacer ese cambio desde el
portal. El falso éxito está corregido; esa conversión automática no está
implementada. Los apagados normales sobre productos disponibles conservan el
flujo previo, incluida la opción elegida en el diálogo.

## Verificación

- 17 pruebas nuevas de regresión Python, aprobadas.
- 6 pruebas nuevas JavaScript de manejo de respuestas en pantalla, aprobadas.
- Suites existentes aprobadas: catálogo, estados, verificación, cierre, Rappi
  sync y backup.
- Arranque simulado y HTTP local: versión 6.9, HTML, encolado, 404 y cancelación.
- Compilación Python y revisión de espacios del diff.
- Sin validación visual ni contra portales reales; la descarga de Chromium
  falló en este entorno. Las pruebas de adaptadores usan dobles controlados.

## Actualización

Los archivos deben llegar a la raíz de `guerrasur/todo-selector`, rama `main`,
conservando sus rutas. Una vez subidos, cerrar la app y volver a abrir mediante
`iniciar_app.bat` o el acceso directo TODO-SELECTOR. El actualizador existente
baja main al arrancar: git pull en clones o ZIP de GitHub en instalaciones sin git.
No se cambiaron el lanzador, el actualizador, las dependencias ni el esquema de
la base de datos. No hace falta borrar datos ni configurar de nuevo las tiendas.
