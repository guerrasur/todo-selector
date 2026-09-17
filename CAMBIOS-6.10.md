# Todo-Selector 6.10 — limpieza de duplicados

Base verificada: main `f8366067fd50d98f46fb031e6330ba30be7d04ce` (6.9),
idéntica a los archivos de la entrega anterior. Fecha: 2026-09-17.

## Uso

1. Actualizar la app a 6.10.
2. Abrir Actualizar carta → Revisar duplicados.
3. Leer las filas Conservar / Archivar copia, con su nombre exacto por portal.
4. Pulsar Archivar N copias. No opera en los portales. Hace backup previo.
5. Volver a leer los portales para confirmar los estados.
6. Para revertir, usar Deshacer: limpiar duplicados en Carta.

## Criterio

Un nombre mostrado con (2) o (PedidosYa) no prueba que sea un duplicado. La
comparación usa el vínculo exacto: mismo nombre remoto en la MISMA plataforma.
Los nombres parecidos, tamaños, tildes y productos con/sin ingredientes no se
normalizan ni se agrupan por parecido. Turbo y Común son destinos distintos.

Una fila conservada debe cubrir todos los vínculos del grupo. Si hay varias,
se priorizan vínculos, estados leídos, categoría manual/existente e id estable.
Una copia sin categoría ni lectura puede archivarse sin perder la fila útil.
Si los estados se contradicen o hay fallos, se deja sin leer hasta releer.

No se limpian grupos con operaciones pendientes/en curso, diferencias de pausa,
categorías manuales incompatibles o nombres distintos en otra plataforma. Se
muestra el motivo. No se eliminan automáticamente filas por ausencia de una
lectura del portal: podría ser una lectura parcial.

## Conservación

Se archivan las filas con activo=False; los ids, vínculos e historial permanecen.
La búsqueda por nombre, el volcado de estados y las acciones ignoran archivados.
Deshacer restaura las filas y metadatos afectados, conservando lecturas/acciones
nuevas del resto del catálogo. La firma del previo evita aplicar un plan viejo;
una transacción SQLite impide insertar órdenes durante el archivado.

## Prevención

La fusión ya no vuelve a separar nombres remotos iguales. Se deduplican los
productos a procesar antes de separar/absorber al vincular varias plataformas.

## Validación

15 pruebas nuevas Python; pruebas JavaScript del flujo de revisión; backup
SQLite real; suites existentes de catálogo, estados, verificación, cierre,
Rappi sync y backup; 17 regresiones de 6.9. JavaScript y Python compilados.
No se validaron Chromium ni los portales reales; tampoco se accedió a la base
local del usuario. El botón realiza el diagnóstico y la limpieza en esa PC.

## Distribución

Paquete incremental sobre 6.9. Subir el contenido de SUBIR_A_GITHUB a main
manteniendo rutas. Cerrar la app y su consola y abrir el lanzador para recibir
6.10. Se conserva el autoupdate, las dependencias y el esquema de datos.
La limitación de duración indefinida documentada en 6.9 sigue vigente.
