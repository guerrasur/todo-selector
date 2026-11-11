# Precios de PedidosYa: primera etapa

El ajuste opcional `pedidosya_precios_url` recibe el enlace completo del
portal `menu-management-v2`. Se valida host, ruta, país Argentina y una sola
pareja `vendor` / `activeMenuId`, y se guarda una URL canónica. No sustituye
`pedidosya_menu_id`, usado por el portal de disponibilidad anterior.

`DestinoPreciosPedidosYa` permite congelar esa pareja como contexto y exigir
que la URL siga representando el mismo local y menú. El orden de parámetros,
su codificación y parámetros accesorios no cambian la identidad. Cambiar
cualquiera de las dos IDs sí la cambia.

El gestor ya puede obtener ese contexto, pero PedidosYa sigue excluido de
las tiendas de precios ejecutables. Una llamada directa a la API explica
que la integración sigue en desarrollo, antes de navegar o editar.
No hay selectores nuevos de lectura/escritura ni se modificaron los flujos
de disponibilidad, CAPTCHA o Rappi. Las guardas del destino aún deben
integrarse con la lectura y cada paso de escritura cuando existan.

## Evidencia necesaria para la siguiente etapa

- HTML del contenedor de la lista, con una categoría abierta y productos
  donde se vean nombre, precio y control para editar.
- HTML del formulario/panel que aparece al editar un producto: identidad,
  precio, botón de guardar y cualquier confirmación posterior.
- Si hay paginación o carga al desplazar, HTML de esos controles.

Para compartir basta copiar el outerHTML de esos contenedores desde Elements
de DevTools. No hace falta una exportación de red, cookies ni tokens.
No incorporar IDs ni productos reales al repo público: usar fixtures ficticias.

La implementación posterior debe compartir el lock de PedidosYa con las
operaciones de disponibilidad, respetar la congelación manual/CAPTCHA y
comprobar local, menú, producto y precio antes de guardar. Solo debe afirmar
éxito tras recargar y releer el precio; no reintentar una escritura incierta.

## Pruebas de esta etapa

```
python pruebas/probar_pedidosya_precios_destino.py
python pruebas/probar_precios.py
```

28 pruebas pasan sin conectarse a los portales reales. Incluyen validación y
persistencia del ajuste, cambio de contexto, rechazo de ejecución de PedidosYa
y regresiones de los planes/lotes de Rappi.
