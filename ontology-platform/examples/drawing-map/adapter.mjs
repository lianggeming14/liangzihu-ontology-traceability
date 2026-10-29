// Display scale is deliberately not named metresPerPoint. No georeferencing is implied.
export function paperToScene(point,{origin=[0,0],scale=1}={}){
 if(!Array.isArray(point)||point.length!==2||!point.every(Number.isFinite)||!Array.isArray(origin)||origin.length!==2||!origin.every(Number.isFinite)||!Number.isFinite(scale)||scale<=0)throw Error('Invalid paper transform');
 return[(point[0]-origin[0])*scale,0,(point[1]-origin[1])*scale];
}
export function featureIdentity(feature){return{entityId:feature.entity_id,spatialId:feature.feature_id};}
export async function fetchAll(path,params={},loader=fetch,{collection='features',expectedDigest=null}={}){
 let cursor=null,digest=expectedDigest;const seen=new Set(),items=[];
 do{
  const query=new URLSearchParams({...params,limit:1000});if(cursor)query.set('cursor',cursor);
  const response=await loader(path+'?'+query.toString());if(!response.ok)throw Error('GIS request failed: '+response.status);
  const page=await response.json();
  if(typeof page.content_sha256!=='string'||(digest!==null&&digest!==page.content_sha256))throw Error('Dataset version changed; reload all pages');
  digest=page.content_sha256;if(!Array.isArray(page[collection]))throw Error('Invalid GIS response');items.push(...page[collection]);
  cursor=page.next_cursor;if(cursor){if(seen.has(cursor))throw Error('Repeated pagination cursor');seen.add(cursor);}
  if(seen.size>10000)throw Error('Page budget exceeded');
 }while(cursor);
 return items;
}
