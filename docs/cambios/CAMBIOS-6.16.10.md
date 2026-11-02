# 6.16.10 — Comprobar la tienda con el pop-up abierto

- La lectura del encabezado de tienda admite el fondo marcado como inert
  o aria-hidden por el modal de confirmación. Antes podía informar un cambio
  de tienda y detenerse justo antes de pulsar «Sí, desactivar».
- Conserva las comprobaciones de URL, nombre, caché y selector único dentro
  de pantalla. No cambia atributos ni fuerza clics en el fondo del modal.
- Los filtros y dropdowns siguen excluyendo elementos inertes u ocultos.

Pruebas locales: apagado por hoy e indefinido con guarda real y JS de
geometría sobre cajas controladas; cambios de nombre, URL y caché bloquean
la confirmación. Regresiones de filtros, selección, dropdowns y tanda.
Pendiente validar en el portal real.
