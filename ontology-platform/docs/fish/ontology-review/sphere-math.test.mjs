import test from 'node:test';
import assert from 'node:assert/strict';
import * as math from './sphere-math.mjs';

test('rotation moves the front pole to the right and preserves three dimensional distance',()=>{
  assert.equal(typeof math.rotatePoint,'function');
  const p=math.rotatePoint([0,0,1],Math.PI/2,0);
  assert.ok(Math.abs(p[0]-1)<1e-12);assert.ok(Math.abs(p[2])<1e-12);
  const q=math.rotatePoint([1,2,3],.7,-.3);assert.ok(Math.abs(Math.hypot(...q)-Math.sqrt(14))<1e-12);
});
test('perspective makes front nodes larger while invalid zoom and depth remain finite',()=>{
  assert.equal(typeof math.projectPoint,'function');
  const front=math.projectPoint([.5,0,1],{width:800,height:600,zoom:1});
  const back=math.projectPoint([.5,0,-1],{width:800,height:600,zoom:1});
  assert.ok(front.x>back.x);assert.ok(front.scale>back.scale);assert.equal(front.y,300);
  for(const zoom of [NaN,Infinity,-Infinity,-9,100]){
    const p=math.projectPoint([0,0,999],{width:800,height:600,zoom});assert.ok([p.x,p.y,p.scale,p.depth].every(Number.isFinite));
    assert.ok(math.clampZoom(zoom)>=.55&&math.clampZoom(zoom)<=2.6);
  }
});
test('sphere layout is deterministic and every class is on the unit sphere',()=>{
  assert.equal(typeof math.spherePoints,'function');
  const a=math.spherePoints(178);assert.deepEqual(a,math.spherePoints(178));assert.equal(a.length,178);
  assert.equal(new Set(a.map(p=>p.join(','))).size,178);a.forEach(p=>assert.ok(Math.abs(Math.hypot(...p)-1)<1e-12));
});
test('a drag remains a drag even when the pointer returns to its start',()=>{
  assert.equal(typeof math.pointerGesture,'function');
  const drag=math.pointerGesture(10,10);drag.move(30,10);drag.move(10,10);assert.equal(drag.isClick(),false);
  const click=math.pointerGesture(10,10);click.move(12,12);assert.equal(click.isClick(),true);
});
test('picking favors the visible front node and tests the actual edge segment',()=>{
  assert.equal(typeof math.pickTarget,'function');
  const nodes=[{id:'back',x:10,y:10,depth:-1,radius:6},{id:'front',x:10,y:10,depth:1,radius:6}];
  assert.equal(math.pickTarget(10,10,nodes,[]).item.id,'front');
  const edges=[{id:'edge',a:{x:0,y:0},b:{x:100,y:0}}];
  assert.equal(math.pickTarget(50,2,[],edges).item.id,'edge');assert.equal(math.pickTarget(150,2,[],edges),null);
});
test('a self relation can be picked on its loop without inventing another endpoint',()=>{
  const loop={id:'self',a:{x:20,y:20},b:{x:20,y:20},loop:{x:20,y:8,radius:12}};
  assert.equal(math.pickTarget(32,8,[],[loop])?.item.id,'self');assert.equal(math.pickTarget(20,8,[],[loop]),null);
});
