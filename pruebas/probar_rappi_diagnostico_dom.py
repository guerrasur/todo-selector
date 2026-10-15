"""Ejecuta el JS de producción sobre HTML con linkedom (solo desarrollo).

npm install --prefix /tmp/rappi-dom-test linkedom --no-audit --no-fund
NODE_PATH=/tmp/rappi-dom-test/node_modules python pruebas/probar_rappi_diagnostico_dom.py
No requiere conexión a Rappi ni cambia disponibilidad.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plataformas.rappi_carta import CartaRappi


def fila(nombre, aria, descripcion=True):
    desc = ('<div data-component="menu-product-description"><p class="font-body-medium">Descripción</p>'
            '<button>Ver más</button></div>') if descripcion else ''
    return (f'<div><div class="flex items-center justify-between"><div><div><img alt=""></div>'
            f'<div><div><p class="font-body-medium text-strong">{nombre}</p></div>{desc}'
            '<div data-component="menu-product-tags"><p class="font-body-medium">Etiqueta</p></div>'
            '</div></div><div><div><span>Precio</span><span>$100</span></div>'
            '<div data-component="menu-item-availability-switch">'
            f'<button role="switch" aria-checked="{aria}" data-state="closed">'
            '<span data-state="checked"></span></button></div>'
            '<button aria-label="Editar"><svg></svg></button></div></div><div class="h-px"></div></div>')


def capturar(markup):
    runner = r'''
const fs = require('fs');
const {parseHTML} = require('linkedom');
const {html, script} = JSON.parse(fs.readFileSync(0, 'utf8'));
global.document = parseHTML('<html><head></head><body>'+html+'</body></html>').document;
const antes = document.toString();
const salida = (new Function('return ('+script+')();'))();
if (antes !== document.toString()) throw Error('El diagnóstico modificó el DOM');
process.stdout.write(JSON.stringify(salida));
'''
    r = subprocess.run(['node', '-e', runner], input=json.dumps(
        {'html': markup, 'script': CartaRappi.JS_CAPTURAR_CARTA}),
        text=True, capture_output=True)
    if r.returncode:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


class DiagnosticoDOM(unittest.TestCase):
    def test_22_filas_completas_sin_alterar_dom(self):
        nombres = [f'Producto ficticio {i}' for i in range(22)]
        d = capturar(''.join(fila(n, 'true' if i % 2 else 'false', i % 3)
                            for i, n in enumerate(nombres)))
        self.assertEqual(d['nombres_dom'], nombres)
        self.assertEqual(d['switches_dom'], 22)
        self.assertEqual([f['nombre'] for f in d['filas']], nombres)
        self.assertEqual([f['disponible'] for f in d['filas']], [bool(i % 2) for i in range(22)])

    def test_nombre_exacto_prefijos_y_duplicados_se_conservan(self):
        d = capturar(fila('Ejemplo', 'true') + fila('Ejemplo chico', 'false') + fila('Ejemplo', 'false'))
        self.assertEqual([f['nombre'] for f in d['filas']], ['Ejemplo', 'Ejemplo chico', 'Ejemplo'])

    def test_aria_invalido_no_se_infiere_de_span_checked(self):
        d = capturar(fila('Ejemplo', 'mixed'))
        self.assertIsNone(d['filas'][0]['disponible'])
        self.assertEqual(d['filas'][0]['aria'], 'mixed')

    def test_cero_filas_y_categoria_no_se_convierten_en_producto(self):
        d = capturar('<p class="font-body-medium">Título</p>'
            '<div data-component="menu-item-availability-switch"><button role="switch" aria-checked="true"></button></div>')
        self.assertEqual(d['filas'], [])
        self.assertEqual(d['nombres_dom'], ['Título'])
        self.assertEqual(d['switches_dom'], 1)


if __name__ == '__main__':
    unittest.main()
