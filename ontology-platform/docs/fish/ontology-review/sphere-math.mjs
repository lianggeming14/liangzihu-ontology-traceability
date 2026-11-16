const finite=(value,fallback=0)=>Number.isFinite(value)?value:fallback;
export const clampZoom=value=>Math.min(2.6,Math.max(.55,finite(value,1)));
export function rotatePoint([x,y,z],yaw=0,pitch=0){
  const cy=Math.cos(finite(yaw)),sy=Math.sin(finite(yaw)),cx=Math.cos(finite(pitch)),sx=Math.sin(finite(pitch));
  const rx=x*cy+z*sy,rz=z*cy-x*sy;
  return [rx,y*cx-rz*sx,y*sx+rz*cx];
}
export function projectPoint([x,y,z],{width=800,height=600,zoom=1}={}){
  const depth=Math.min(1.5,Math.max(-1.5,finite(z))),scale=3/(3-depth);
  const radius=Math.min(Math.max(1,finite(width,800)),Math.max(1,finite(height,600)))*.37*clampZoom(zoom);
  return {x:finite(width,800)/2+finite(x)*radius*scale,y:finite(height,600)/2+finite(y)*radius*scale,scale,depth};
}
export function spherePoints(count){
  const n=Math.max(0,Math.floor(finite(count))),angle=Math.PI*(3-Math.sqrt(5));
  return Array.from({length:n},(_,i)=>{const y=1-2*(i+.5)/n,r=Math.sqrt(1-y*y),theta=i*angle;return [Math.cos(theta)*r,y,Math.sin(theta)*r];});
}
export function pointerGesture(startX,startY,threshold=5){
  let x=startX,y=startY,moved=false;
  return {move(nextX,nextY){if(Math.hypot(nextX-startX,nextY-startY)>threshold)moved=true;const delta={x:nextX-x,y:nextY-y};x=nextX;y=nextY;return delta;},isClick:()=>!moved};
}
function distanceToSegment(x,y,a,b){
  const dx=b.x-a.x,dy=b.y-a.y,len=dx*dx+dy*dy,t=len?Math.max(0,Math.min(1,((x-a.x)*dx+(y-a.y)*dy)/len)):0;
  return Math.hypot(x-a.x-t*dx,y-a.y-t*dy);
}
export function pickTarget(x,y,nodes,edges){
  const node=nodes.filter(n=>Math.hypot(n.x-x,n.y-y)<=Math.max(8,n.radius||0)).sort((a,b)=>b.depth-a.depth)[0];
  if(node)return {kind:'node',item:node};
  let chosen=null,best=5;
  for(const edge of edges){const distance=edge.loop?Math.abs(Math.hypot(x-edge.loop.x,y-edge.loop.y)-edge.loop.radius):distanceToSegment(x,y,edge.a,edge.b);if(distance<best){best=distance;chosen=edge;}}
  return chosen?{kind:'edge',item:chosen}:null;
}
