import test from 'node:test';
import assert from 'node:assert/strict';
import {paperToScene, fetchAll, featureIdentity} from './adapter.mjs';

test('every stream must match the directory snapshot',async()=>{
 await assert.rejects(fetchAll('/features',{},async()=>({ok:true,json:async()=>({content_sha256:'new',features:[],next_cursor:null})}),{expectedDigest:'old'}),/version/);
});

test('paper positions remain unitless display coordinates, not geographic positions',()=>{
 assert.deepEqual(paperToScene([10,20],{origin:[5,10],scale:2}),[10,0,20]);
 assert.throws(()=>paperToScene([NaN,1]));
 assert.throws(()=>paperToScene([1,2],{scale:0}));
});
test('map identity preserves both ontology UUID and spatial representation ID',()=>{
 assert.deepEqual(featureIdentity({entity_id:'uuid',feature_id:'DRAW-1'}),{entityId:'uuid',spatialId:'DRAW-1'});
});
test('all pages are read and a changed version or loop fails',async()=>{
 let calls=0;
 const loader=async()=>({ok:true,json:async()=>({content_sha256:'a',features:[++calls],next_cursor:calls===1?'next':null})});
 assert.deepEqual(await fetchAll('/features',{},loader),[1,2]);
 await assert.rejects(fetchAll('/features',{},async()=>({ok:true,json:async()=>({content_sha256:'a',features:[],next_cursor:'same'})})),/cursor/);
 let n=0;await assert.rejects(fetchAll('/features',{},async()=>({ok:true,json:async()=>({content_sha256:String(++n),features:[],next_cursor:'next'})})),/version/);
});
