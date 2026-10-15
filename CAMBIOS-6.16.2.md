# v6.16.2 — Selector de tienda duplicado

El portal renderiza dos botones con data-component=store-select. El click
sin filtrar fallaba con strict mode violation y la comprobación del nombre
exigía erróneamente que existiera un solo nodo en todo el documento.

Ahora apertura, lectura y confirmación usan el mismo detector geométrico:
se ignoran copias ocultas/fuera del viewport y se exige una única visible.
La confirmación ya no toma el primer querySelector del documento.

Validación: 10 pruebas de filtro, geometría y duplicados más 6 pruebas de
selección por ids aprobadas; compilación y diff correctos. Pendiente prueba
en vivo. No se modifican catálogo, cola ni credenciales.
