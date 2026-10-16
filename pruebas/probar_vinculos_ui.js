// Dashboard y vinculación completa, con DOM controlado y sin portales.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(require('node:path').join(__dirname,'../static/index.html'),'utf8');
for(const s of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) new vm.Script(s[1]);
const source=(a,b)=>html.slice(html.indexOf(a),html.indexOf(b,html.indexOf(a)));
class Element {
 constructor(tag){this.tag=tag;this.children=[];this.style={};this.dataset={};this.classList={add(){},remove(){}};this.value='';this.textContent='';}
 append(...els){this.children.push(...els);}
 appendChild(el){this.append(el);return el;}
 set innerHTML(s){this.children=[];}
 setAttribute(){}
}
const all=e=>[e,...e.children.flatMap(all)];
const PLATS=['pedidosya','rappi','rappi_comun'];
const nodes=Object.fromEntries(['lista','resultado-busqueda','cuenta-prendidos'].map(id=>[id,new Element('div')]));
let operables=[],corregidos=[];
const ctx={document:{createElement:t=>new Element(t),getElementById:id=>nodes[id]},
 PLATS,NOMBRE_PLAT:{pedidosya:'PedidosYa',rappi:'Turbo',rappi_comun:'Común'},
 filtro:'',vista:'todos',coincide:()=>true,grupoDe:()=> 'prendido',
 porCategoria:(cont,items)=>{operables=items;return items.length;},
 titulo:t=>Object.assign(new Element('h3'),{textContent:t}),fila:()=>new Element('operacion'),
 completarVinculo:async item=>corregidos.push(item.id),revisarDuplicados:async()=>{},
};
vm.createContext(ctx);
vm.runInContext(source('function revisionDe(', '\nfunction porCategoria('),ctx);
const completo={id:1,nombre:'Plato completo',estados:Object.fromEntries(PLATS.map(p=>[p,{}]))};
const incompleto={id:2,nombre:'Plato (PedidosYa)',estados:{pedidosya:{}}};
const duplicado={...completo,id:3,nombre:'<img src=x>',revision_vinculos:{faltantes:[],duplicados:['pedidosya']}};
ctx.pintarProductos([completo,incompleto,duplicado]);
assert.deepEqual(operables.map(p=>p.id),[1]);
const pendientes=nodes.lista.children.find(e=>e.tag==='details');
assert(pendientes);assert.match(pendientes.children[0].textContent,/2/);
assert.equal(all(pendientes).filter(e=>e.tag==='button').length,2);
assert(all(pendientes).some(e=>e.textContent.includes('<img src=x>')));
ctx.pintarProductos([incompleto]);
assert(nodes.lista.children.some(e=>e.tag==='details'));
assert.equal(nodes.lista.textContent,'');

let enviados=[],alertas=[];
Object.assign(ctx,{borradorVinculo:{pedidosya:'Plato'},nombreVinculo:'',
 platsCarta:()=>PLATS,todosLosNombres:()=>['Plato'],vinculoActual:()=>null,
 productoDe:()=>null,columnasDeLaFila:()=>{},
 alert:t=>alertas.push(t),accionCarta:(url,data)=>enviados.push({url,data})});
vm.runInContext(source('function vinculadorManual()', '\nfunction grupo('),ctx);
let editor=ctx.vinculadorManual();
let selects=all(editor).filter(e=>e.tag==='select');
const boton=all(editor).find(e=>e.tag==='button');
boton.onclick();assert.equal(enviados.length,0);assert.equal(alertas.length,1);
for(const s of selects){s.value='Plato';s.onchange();}
const nombre=all(editor).find(e=>e.tag==='input');nombre.value='Nombre común';nombre.oninput();
// Volver a dibujar no pierde el trabajo de vinculación.
editor=ctx.vinculadorManual();selects=all(editor).filter(e=>e.tag==='select');
assert(selects.every(e=>e.value==='Plato'));
all(editor).find(e=>e.tag==='button').onclick();
assert.equal(enviados.length,1);assert.equal(enviados[0].data.nombre,'Nombre común');
assert.deepEqual(Object.keys(enviados[0].data.nombres),PLATS);
console.log('UI OK: una fila operable, pendientes visibles, sin botones parciales, vínculos completos y borrador persistente');
