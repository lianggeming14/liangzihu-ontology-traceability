import test from 'node:test';
import assert from 'node:assert/strict';
import * as sphere from './ontology-sphere.mjs';
import {readRoute} from './model.mjs';
const fixture={contract:'lzo-ontology-network/1',nodes:[{iri:'a',label:'塘口',role:'spatial',instance_count:4},{iri:'b',label:'摄像头',role:'device',instance_count:2}],edges:[{id:'ab',source:'a',target:'b',predicate:'has',kind:'observed',count:2},{id:'bad',source:'a',target:'missing',predicate:'has',kind:'observed',count:1}],counts:{classes:2}};
test('network accepts its main entry route',()=>assert.equal(readRoute('#view=network').view,'network'));
test('network draws supplied edges only and excludes unresolved endpoints',()=>{
  assert.equal(typeof sphere.prepareNetwork,'function');const net=sphere.prepareNetwork(fixture);
  assert.equal(net.nodes.length,2);assert.deepEqual(net.edges.map(x=>x.id),['ab']);assert.equal(net.omitted,1);
});
test('predicate and category filters retain only actual relationships between visible nodes',()=>{
  assert.equal(typeof sphere.filterNetwork,'function');const net=sphere.prepareNetwork(fixture);
  assert.equal(sphere.filterNetwork(net,{predicate:'other'}).edges.length,0);
  const filtered=sphere.filterNetwork(net,{role:'device'});assert.deepEqual(filtered.nodes.map(x=>x.iri),['b']);assert.equal(filtered.edges.length,0);
});
test('destroy removes pointer listeners and cancels pending draw; late loads cannot mutate a new release',async()=>{
  assert.equal(typeof sphere.createViewSession,'function');
  const target=new EventTarget();let callbacks=new Map(),calls=0,drawn=0,cancelled=0,next=0;
  const frame={requestAnimationFrame:fn=>{callbacks.set(++next,fn);return next;},cancelAnimationFrame:id=>{callbacks.delete(id);cancelled++;}};
  let current='release-1';const session=sphere.createViewSession('release-1',()=>current,frame);
  session.listen(target,'pointerdown',()=>calls++);target.dispatchEvent(new Event('pointerdown'));assert.equal(calls,1);
  session.schedule(()=>drawn++);let resolve;const pending=session.load(()=>new Promise(done=>resolve=done),()=>calls++);
  await Promise.resolve();current='release-2';resolve({release_id:'release-1'});await pending;assert.equal(calls,1);
  session.destroy();target.dispatchEvent(new Event('pointerdown'));assert.equal(calls,1);assert.equal(callbacks.size,0);assert.equal(cancelled,1);assert.equal(drawn,0);
});
test('a mismatched response release is rejected even before unmount',async()=>{
  assert.equal(typeof sphere.createViewSession,'function');let applied=false;
  const session=sphere.createViewSession('release-1',()=> 'release-1',{});
  await assert.rejects(()=>session.load(async()=>({release_id:'release-2'}),()=>applied=true),/版本/);assert.equal(applied,false);session.destroy();
});
test('a late failed relation page cannot replace the newer successful selection with an error',async()=>{
  const session=sphere.createViewSession('release-1',()=> 'release-1',{});let reject,shown='';
  const old=session.load(()=>new Promise((resolve,fail)=>reject=fail),()=>shown='old');
  await session.load(async()=>({release_id:'release-1'}),()=>shown='new');reject(Error('old network failure'));
  assert.equal(await old,false);assert.equal(shown,'new');session.destroy();
});
