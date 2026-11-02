# 6.16.5 — Diagnóstico de Rappi

Versión de detección solicitada para investigar por qué hay productos en el
HTML que el selector actual no consigue leer.

- Al arrancar revisa Turbo y Común una vez, usando la pestaña compartida.
- Registra nombres del DOM, cantidad de switches, filas reconocidas,
  aria-checked y resultados del selector anterior por producto.
- No apaga ni prende productos ni cambia precios en Rappi.
- Conserva sus operaciones pendientes sin gastar intentos. Las lecturas,
  revalidaciones y operaciones posteriores de Rappi quedan en pausa.
- Muestra «Rappi: diagnóstico · acciones en pausa». PedidosYa sigue normal.

Actualizar, reiniciar y enviar el log desde RAPPI DIAGNOSTICO hasta los
DIAG_RAPPI_FIN de ambas tiendas; si aparece DIAG_RAPPI_ERROR, incluirlo.
No hace falta pulsar Revalidar ni enviar operaciones de prueba.

Validación local: ejecución del JS real sobre HTML representativo con 22
productos, descripciones opcionales, duplicados, aria inválido y cero filas;
comprobación de que no modifica el DOM. Pruebas del arranque, cola en pausa,
bloqueo de navegación y precios, y regresiones existentes. La ejecución en
el portal real queda pendiente del log de esta versión.
