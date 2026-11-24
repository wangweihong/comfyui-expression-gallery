// Keep the three useful gallery outputs when loading earlier saved workflows.
export const outputNames=['image','expression_en','expression_zh'];

export function migrateExpressionOutputs(workflow){
 const plans=[];
 function visit(value){
  if(!value||typeof value!=='object')return;
  if(Array.isArray(value.nodes)){
   for(const node of value.nodes){
    if(node.type!=='ExpressionClayGallery'||!Array.isArray(node.outputs)||!node.outputs.length)continue;
    if(node.outputs.length===3&&outputNames.every((name,index)=>node.outputs[index]?.name===name))continue;
    const slots=new Map(node.outputs.map((port,index)=>[index,outputNames.indexOf(port.name)]));
    const unsupported=new Set();
    for(const [slot,next] of slots)if(next<0&&node.outputs[slot].links?.length)unsupported.add(node.outputs[slot].name);
    for(const link of value.links||[]){
     const origin=Array.isArray(link)?link[1]:link.origin_id,slot=Array.isArray(link)?link[2]:link.origin_slot;
     if(String(origin)===String(node.id)&&!(slots.get(slot)>=0))unsupported.add(node.outputs[slot]?.name||String(slot));
    }
    if(unsupported.size)throw new Error('Expression Gallery: 旧输出仍有连线 / Remove connections from retired outputs before loading: '+[...unsupported].join(', '));
    const ports=outputNames.map((name,index)=>{
     const port=node.outputs.find(port=>port.name===name);
     return {...port,name,type:index===0?'IMAGE':'STRING',links:port?.links||null,slot_index:index};
    });
    plans.push({graph:value,node,slots,ports});
   }
  }
  for(const nested of Object.values(value)){
   if(Array.isArray(nested))nested.forEach(visit);else if(nested&&typeof nested==='object')visit(nested);
  }
 }
 visit(workflow);
 // Validate the entire workflow before changing any output or connection.
 for(const {graph,node,slots,ports} of plans){
  for(const link of graph.links||[]){
   if(Array.isArray(link)){if(String(link[1])===String(node.id))link[2]=slots.get(link[2]);}
   else if(String(link.origin_id)===String(node.id))link.origin_slot=slots.get(link.origin_slot);
  }
  node.outputs=ports;
 }
 return workflow;
}
