import test from 'node:test';
import assert from 'node:assert/strict';
import {migrateExpressionOutputs,outputNames} from '../web/output_migration.mjs';
const legacyNames=['image','width','height','expression_id','expression_en','expression_zh','description','expression_types_en','facial_actions_en','intensity_en','tags_json'];
function fixture(){
 return {nodes:[{id:1,type:'ExpressionClayGallery',widgets_values:['F01HA','zh'],outputs:legacyNames.map((name,index)=>({name,type:index===0?'IMAGE':index<3?'INT':'STRING',links:({0:[1],4:[2],5:[3]})[index]||null}))},{id:2,type:'Other',outputs:[]}],links:[[1,1,0,2,0,'IMAGE'],[2,1,4,2,1,'STRING'],[3,1,5,2,2,'STRING']]};
}
test('compacts old ports while preserving image and bilingual text connections',()=>{
 const graph=fixture(),widgets=structuredClone(graph.nodes[0].widgets_values);
 migrateExpressionOutputs(graph);
 assert.deepEqual(graph.nodes[0].outputs.map(p=>p.name),outputNames);
 assert.deepEqual(graph.links.map(l=>l[2]),[0,1,2]);
 assert.deepEqual(graph.nodes[0].outputs.map(p=>p.links),[[1],[2],[3]]);
 assert.deepEqual(graph.nodes[0].widgets_values,widgets);
 assert.deepEqual(migrateExpressionOutputs(structuredClone(graph)),graph);
});
test('also migrates nested subgraphs and object-style links',()=>{
 const nested=fixture();nested.links=nested.links.map(([id,origin_id,origin_slot,target_id,target_slot,type])=>({id,origin_id,origin_slot,target_id,target_slot,type}));
 const workflow={nodes:[],links:[],definitions:{subgraphs:[nested]}};
 migrateExpressionOutputs(workflow);assert.deepEqual(nested.links.map(l=>l.origin_slot),[0,1,2]);
});
test('refuses to silently drop connected retired outputs without modifying the workflow',()=>{
 const first=fixture(),second=fixture();second.nodes[0].outputs[1].links=[4];second.links.push([4,1,1,2,3,'INT']);
 const workflow={definitions:{subgraphs:[first,second]}},before=structuredClone(workflow);
 assert.throws(()=>migrateExpressionOutputs(workflow),/width/);assert.deepEqual(workflow,before);
});
test('new nodes without serialized output ports are left for ComfyUI to initialize',()=>{
 const workflow={nodes:[{id:1,type:'ExpressionClayGallery',widgets_values:['F01HA','en']}],links:[]},before=structuredClone(workflow);
 assert.deepEqual(migrateExpressionOutputs(workflow),before);
});
