// node pruebas/probar_duplicados_ui.js — contrato de interacción, sin navegador.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../static/index.html'),'utf8');
const begin=html.indexOf('async function revisarDuplicados()');
const source=html.slice(begin,html.indexOf('\nasync function leerCarta()',begin));
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.textContent='';this.style={};}
  appendChild(e){this.children.push(e);return e;}
  replaceChildren(){this.children=[];}
}
function setup(plan,post={ok:true,archivados:1}) {
 const cont=new Element('div'),requests=[];let refreshed=0;
 const ctx={document:{createElement:t=>new Element(t),getElementById:()=>cont},
  NOMBRE_PLAT:{pedidosya:'PedidosYa'},
  fetch:async(url,options)=>{requests.push({url,options});return {ok:options?post.ok:true,json:async()=>options?post:plan};},
  refrescarCarta:async()=>{refreshed++;cont.replaceChildren();},cargar:async()=>{}};
 vm.createContext(ctx);vm.runInContext(source,ctx);
 return {ctx,cont,requests,get refreshed(){return refreshed;}};
}
const fila={id:1,nombre:'<img src=x onerror=alert(1)>',plataformas:{pedidosya:'Plato'}};
const plan={firma:'firma-del-previo',total:1,grupos:[{conservar:fila,archivar:[{...fila,id:2,nombre:'Plato (2)'}]}],revisar:[]};
(async()=>{
 let t=setup(plan);await t.ctx.revisarDuplicados();
 assert.equal(t.requests.length,1);assert.equal(t.requests[0].options,undefined);
 assert(t.cont.children.find(e=>e.tag==='section').children[0].textContent.includes(fila.nombre));
 const button=t.cont.children.find(e=>e.tag==='button');
 assert.equal(button.textContent,'Archivar 1 copia');await button.onclick();
 assert.equal(JSON.parse(t.requests[1].options.body).firma,plan.firma);
 assert.equal(t.refreshed,1);assert.match(t.cont.textContent,/Se archivaron 1 copias/);
 t=setup(plan,{ok:false,detail:'El catálogo cambió'});await t.ctx.revisarDuplicados();
 await t.cont.children.find(e=>e.tag==='button').onclick();
 assert.equal(t.refreshed,0);assert.match(t.cont.children[0].textContent,/El catálogo cambió/);
 t=setup({firma:'x',total:0,grupos:[],revisar:[{filas:[fila],motivo:'Vínculos distintos'}]});await t.ctx.revisarDuplicados();
 assert(!t.cont.children.some(e=>e.tag==='button'));
 assert.match(t.cont.children.find(e=>e.tag==='section').children[0].textContent,/Vínculos distintos/);
 console.log('UI duplicados OK: vista previa, texto seguro, confirmación, firma vencida y conflictos');
})().catch(e=>{console.error(e);process.exitCode=1;});
