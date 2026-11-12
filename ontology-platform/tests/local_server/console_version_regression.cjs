// Execute the actual console script with deterministic delayed HTTP responses.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
class Element{
  constructor(){this.listeners={};this._html='';this._text='';this.value='';this.hidden=false;this.disabled=false;}
  addEventListener(name,fn){this.listeners[name]=fn;}
  set innerHTML(value){this._html=value;this._text='';} get innerHTML(){return this._html;}
  set textContent(value){this._text=String(value);this._html=String(value);} get textContent(){return this._text;}
}
const elements=new Map(), element=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const anchors=[new Element(),new Element()];
const document={listeners:{},getElementById:element,querySelectorAll:()=>anchors,addEventListener(name,fn){this.listeners[name]=fn;}};
let active='old',interval;
const requests=[],held=new Map();
const response=value=>({ok:true,status:200,json:async()=>value,headers:{get:()=>null}});
const manifests=id=>({release_id:id,concepts:[{iri:'urn:test:class:ponds',label:id+' class'}]});
const releases=[{release_id:'old',status:'published',legacy_snapshot:true},{release_id:'new',status:'published'}];
const location=new URL('http://127.0.0.1:8792/');
const sandbox={document,location,history:{replaceState(_a,_b,url){location.href=String(url);}},URL,URLSearchParams,AbortController,Blob,console,
  setInterval(fn){interval=fn;return 1;},setTimeout,clearTimeout,
  fetch:async input=>{const url=new URL(String(input),location);const id=url.searchParams.get('release_id');requests.push(url);
    if(url.pathname==='/api/v1/status')return response({status:'ready',release_id:active,active_release:{...releases.find(row=>row.release_id===active),counts:{instances:1}},jobs:[]});
    if(url.pathname==='/api/v1/releases')return response({items:releases,next_offset:null});
    if(url.pathname==='/api/v1/manifest')return response(manifests(id));
    const key=url.pathname+':'+id;
    if(held.has(key))return new Promise(resolve=>held.set(key,resolve));
    if(url.pathname==='/api/v1/instances')return response({release_id:id,items:[{iri:'urn:test:instance:'+id,label:id+' row'}],next_cursor:null});
    if(url.pathname==='/api/v1/resource')return response({release_id:id,outgoing:[{predicate:'urn:p',object:{type:'literal',value:id+' detail'}}],incoming:[],provenance:{data_nature:'synthetic'}});
    throw Error('unexpected fixture URL '+url);
  }};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function select(id){element('release-select').value=id;await element('release-select').listeners.change();}
async function query(){element('class-select').value='urn:test:class:ponds';await element('query-button').listeners.click();}
async function main(){
  const source=fs.readFileSync(process.argv[2],'utf8');
  await vm.runInNewContext('(async()=>{'+source+'\n})()',sandbox);
  assert.equal(element('release-select').value,'old');
  await query();assert.match(element('instances').innerHTML,/old row/);
  held.set('/api/v1/resource:old',null);
  const pending=document.listeners.click({target:{closest:()=>({dataset:{iri:'urn:test:instance:old',releaseId:'old'}})},preventDefault(){}});
  await tick();assert.equal(typeof held.get('/api/v1/resource:old'),'function');
  active='new';await interval();
  assert.equal(element('release-select').value,'old','new active release must not silently replace a selected historical view');
  assert.match(element('new-release-message').textContent,/新版本/);
  await select('new');
  assert.doesNotMatch(element('instances').innerHTML,/old row/);
  assert.doesNotMatch(element('resource').innerHTML,/old detail/);
  held.get('/api/v1/resource:old')(response({release_id:'old',outgoing:[{predicate:'urn:p',object:{type:'literal',value:'LATE OLD DETAIL'}}],incoming:[],provenance:{data_nature:'synthetic'}}));
  await pending;await tick();
  assert.doesNotMatch(element('resource').innerHTML,/LATE OLD DETAIL/,'late old resource response must not refill the new version');
  assert.ok(anchors.every(anchor=>anchor.href.includes('release_id=new')));
  const before=requests.length;
  await document.listeners.click({target:{closest:()=>({dataset:{iri:'urn:test:instance:old',releaseId:'old'}})},preventDefault(){}});
  assert.equal(requests.length,before,'stale old link must never query its IRI in the new version');
  await select('old');held.set('/api/v1/instances:old',null);
  element('class-select').value='urn:test:class:ponds';const oldPage=element('query-button').listeners.click();await tick();
  await select('new');
  held.get('/api/v1/instances:old')(response({release_id:'old',items:[{iri:'urn:test:instance:old',label:'LATE OLD ROW'}],next_cursor:'old-cursor'}));
  await oldPage;await tick();
  assert.doesNotMatch(element('instances').innerHTML,/LATE OLD ROW/);
  assert.equal(element('next-button').hidden,true);
  assert.equal(element('class-select').value,'');
  assert.ok(requests.filter(url=>url.pathname==='/api/v1/resource').every(url=>url.searchParams.get('release_id')==='old'));
  console.log('console version regression passed: selected history, late resource/page rejection, stale links, legacy links');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
