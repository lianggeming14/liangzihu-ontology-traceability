import test from 'node:test';
import assert from 'node:assert/strict';
import * as map from './spatial-map.mjs';
const polygon={type:'Polygon',coordinates:[[[114,30],[115,30],[115,31],[114,30]],[[114.2,30.2],[114.3,30.2],[114.2,30.3],[114.2,30.2]]]};
const feature={id:'a',iri:'urn:a',class_iri:'urn:field',label:'田块',kind:'field',geometry:polygon,attributes:{depth:null},source_refs:[]};
const fixture={contract:'lzo-spatial-map/2',features:[feature,{...feature,id:'b',iri:'urn:b'}],display_features:[{id:'piece',kind:'field',geometry:polygon,object_iris:['urn:a','urn:b'],conflict:true}],layers:[],unlocated:[]};
test('overlapping original polygons never render again alongside the reviewed display piece',()=>{
  assert.equal(typeof map.prepareSpatialMap,'function');const result=map.prepareSpatialMap(fixture);
  assert.equal(result.display.length,1);assert.deepEqual(result.display[0].object_iris,['urn:a','urn:b']);
  assert.equal(result.objects.size,2);
});
test('feature bounds include valid facility points but never guess null coordinates',()=>{
  assert.equal(typeof map.geometryBounds,'function');
  assert.deepEqual(map.geometryBounds([polygon,{type:'Point',coordinates:[116,32]},{type:'Point',coordinates:[null,null]}]),[114,30,116,32]);
  assert.equal(map.geometryBounds([{type:'Point',coordinates:[null,null]},null]),null);
});
test('polygon paths retain holes and every multipolygon ring',()=>{
  assert.equal(typeof map.geometryPath,'function');
  const path=map.geometryPath(polygon,p=>p);assert.equal((path.match(/M/g)||[]).length,2);assert.equal((path.match(/Z/g)||[]).length,2);
  const multi=map.geometryPath({type:'MultiPolygon',coordinates:[polygon.coordinates,polygon.coordinates]},p=>p);assert.equal((multi.match(/M/g)||[]).length,4);
});
test('a malformed polygon never drops its invalid exterior and draws its hole as a new field',()=>{
  const invalid={...polygon,coordinates:[[[114,30],[null,30],[115,31],[114,30]],polygon.coordinates[1]]};
  assert.equal(map.geometryPath(invalid,p=>p),'');
  const result=map.prepareSpatialMap({...fixture,features:[{...feature,geometry:invalid}],display_features:[{...fixture.display_features[0],geometry:invalid}]});
  assert.equal(result.display.length,0);assert.equal(result.unlocated.length,1);
});
test('unlocated facilities remain in the directory and long optional lines do not ruin initial fit',()=>{
  assert.equal(typeof map.prepareSpatialMap,'function');
  const data=map.prepareSpatialMap({...fixture,features:[feature,{...feature,id:'no',iri:'urn:no',geometry:null,kind:'facility'},{...feature,id:'road',iri:'urn:road',kind:'road',geometry:{type:'LineString',coordinates:[[110,25],[120,40]]}}]});
  assert.deepEqual(data.unlocated.map(x=>x.iri),['urn:no']);assert.deepEqual(data.bounds,[114,30,115,31]);
});
test('labels and source values are escaped while unknown depth is explicitly preserved',()=>{
  assert.equal(typeof map.featureDetailMarkup,'function');
  const html=map.featureDetailMarkup({...feature,label:'<img src=x onerror=alert(1)>',attributes:{depth:null,notes:'<script>alert(2)</script>'}});
  assert.ok(!html.includes('<img'));assert.ok(!html.includes('<script'));assert.ok(html.includes('&lt;img'));assert.ok(html.includes('未提供'));
});
test('a release with no valid geometry still offers its unlocated business objects',()=>{
  const container=new EventTarget();container.innerHTML='';
  const view=map.mountSpatialMap(container,{...fixture,features:[{...feature,label:'无位置设施',geometry:null}],display_features:[]});
  assert.ok(container.innerHTML.includes('无位置设施'));assert.ok(container.innerHTML.includes('data-unlocated-open'));
  view.destroy();
});
test('an initial same-IRI selection opens its unlocated details even beyond the directory preview',()=>{
  const container=new EventTarget();container.innerHTML='';
  const rows=Array.from({length:27},(_,i)=>({...feature,iri:`urn:facility:${i}`,label:`待定位设施 ${i}`,geometry:null,kind:'facility'}));
  const view=map.mountSpatialMap(container,{...fixture,features:[],unlocated:rows,display_features:[]},{selectedIri:'urn:facility:26'});
  assert.ok(container.innerHTML.includes('待定位设施 26'));assert.ok(container.innerHTML.includes('待定位 · 无坐标'));
  view.destroy();
});
test('producer-marked abnormal road length shows its recorded threshold and fit exclusion',()=>{
  const road={...feature,kind:'road',attributes:{computed_measurements:{length_m:12345.67,method:'geodesic'},exclude_from_initial_fit:true}};
  const quality={anomalous_lengths:[{iri:road.iri,length_m:12345.67,threshold_m:10000,action:'retained_excluded_from_initial_fit'}],initial_fit_exclusions:[road.iri]};
  const html=map.featureDetailMarkup(road,quality);
  assert.match(html,/异常长度/);assert.match(html,/来源判定阈值[^<]*10000 m/);assert.match(html,/已排除初始视野拟合/);assert.match(html,/原几何保留/);
});
test('quality-only anomaly markers remain visible and their reasons are escaped',()=>{
  const road={...feature,kind:'road',attributes:{computed_measurements:{length_m:200},exclude_from_initial_fit:false}};
  const html=map.featureDetailMarkup(road,{anomalous_lengths:[{iri:road.iri,length_m:200,threshold_m:150,action:'retained_excluded_from_initial_fit',reason:'<img src=x onerror=alert(1)>'}]});
  assert.match(html,/异常长度/);assert.match(html,/已排除初始视野拟合/);assert.match(html,/150 m/);assert.ok(!html.includes('<img'));assert.ok(html.includes('&lt;img'));
});
test('an exclusion flag without a quality record is explained without inventing a threshold',()=>{
  const flagged=map.featureDetailMarkup({...feature,kind:'canal',attributes:{exclude_from_initial_fit:true}});
  assert.match(flagged,/已排除初始视野拟合/);assert.match(flagged,/阈值未提供/);
  const unmarked=map.featureDetailMarkup({...feature,kind:'road',attributes:{computed_measurements:{length_m:999999}}},{anomalous_lengths:[{iri:'another-object',length_m:20000,threshold_m:10000}]});
  assert.ok(!unmarked.includes('异常长度'));assert.ok(!unmarked.includes('已排除初始视野拟合'));
});
test('CAD detail uses readable Chinese evidence labels and rounded measurements while retaining exact source values',()=>{
  const row={...feature,nature:'cad_candidate_unverified',position_status:'candidate_approximate',attributes:{
    computed_measurements:{area_m2:5902.310936814407,perimeter_m:381.73544545469997,length_m:null,
      method:'pyproj.Geod WGS84 ellipsoidal geodesic',units:{area:'m2',length:'m',perimeter:'m'},
      assumptions:'Source-declared candidate longitude/latitude; original CAD CRS UNKNOWN; not field verified.'},
    depth_m:null,original_cad_crs_status:'UNKNOWN',registration_status:'candidate_approximate'}};
  const before=structuredClone(row),html=map.featureDetailMarkup(row);
  assert.match(html,/>CAD 候选资料 · 未核验</);assert.match(html,/>候选近似配准 · 待核实</);
  assert.match(html,/>5,902\.31</);assert.match(html,/>381\.74</);assert.match(html,/>未提供</);
  assert.match(html,/>WGS 84 椭球测地线计算（pyproj.Geod）</);
  assert.ok(html.includes('面积 m² · 长度 m · 周长 m'));assert.ok(html.includes('原始 CAD 坐标参考未知，尚未经现场核实'));
  assert.ok(html.includes('查看原始属性与完整精度'));assert.ok(html.includes('原始值：5902.310936814407'));
  assert.ok(html.includes('Source-declared candidate longitude/latitude; original CAD CRS UNKNOWN; not field verified.'));
  assert.deepEqual(row,before);
});
test('unrecognized evidence stays truthful and escaped, and numeric text is never coerced or rounded',()=>{
  const html=map.featureDetailMarkup({...feature,nature:'new_<nature>',position_status:'new_<status>',attributes:{
    computed_measurements:{area_m2:'999999999999.123456789',perimeter_m:0,length_m:Infinity,method:'<img src=x>',
      assumptions:'Unknown <script> premise',units:{area:'custom<unit>',future:'<unit>'}}}});
  assert.ok(html.includes('new_&lt;nature&gt;'));assert.ok(html.includes('new_&lt;status&gt;'));
  assert.match(html,/>999999999999\.123456789</);assert.match(html,/>0\.00</);assert.match(html,/>Infinity</);
  assert.ok(!html.includes('<img'));assert.ok(!html.includes('<script>'));assert.ok(html.includes('&lt;img src=x&gt;'));
  assert.ok(html.includes('custom&lt;unit&gt;'));assert.ok(html.includes('future'));
});
