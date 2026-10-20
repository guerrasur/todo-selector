// node pruebas/probar_verificacion_ui.js — DOM mínimo, sin dependencias.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
for (const bloque of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) {
  new vm.Script(bloque[1]);
}
class Elemento {
  constructor() { this.children = []; this.style = {}; this.textContent = ''; }
  append(...hijos) { this.children.push(...hijos); }
  appendChild(hijo) { this.append(hijo); }
}
const texto = nodo => typeof nodo === 'string' ? nodo
  : nodo.textContent + nodo.children.map(texto).join(' ');
const llamadas = [];
const contexto = {
  document: {createElement: () => new Elemento()},
  NOMBRE_PLAT: {pedidosya: 'PedidosYa', rappi: 'Rappi'},
  PASOS_VERIFICACION: [['Buscá el ', 'código', ' en tu correo.']],
  terminarVerificacion: (plataforma) => llamadas.push(plataforma),
};
vm.createContext(contexto);
const inicio = html.indexOf('function pasoVerificacion(');
const fin = html.indexOf('function actualizarBotonVerificacion()', inicio);
vm.runInContext(html.slice(inicio, fin), contexto);
const cont = new Elemento();
contexto.pintarVerificacion(cont, [{plataforma: 'pedidosya', origen: 'captcha', en_espera: 2}], false);
assert.match(texto(cont), /Press & Hold/);
assert.match(texto(cont), /automáticamente/);
assert.doesNotMatch(texto(cont), /código|correo|dos pasos/);
cont.children[0].children.at(-1).children[0].onclick();
assert.equal(llamadas.pop(), 'pedidosya');
const rappi = new Elemento();
contexto.pintarVerificacion(rappi, [{plataforma: 'rappi', origen: 'manual'}], false);
assert.match(texto(rappi), /código/);
assert.match(texto(rappi), /Ya terminé de verificar/);
assert.doesNotMatch(texto(rappi), /automáticamente/);
console.log('Sintaxis e instrucciones de verificación UI OK');
