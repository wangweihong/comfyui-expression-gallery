export function createAssetTools({getData,language,t,request,tagTools,onSaved,onUploaded}){
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const button=(text,fn,cls)=>{const n=el('button',text,cls);n.type='button';n.onclick=fn;return n;};
 const name=row=>row[language()==='en'?'name_en':'name_zh']||row.id;
 const errorText=error=>t(error.message)||error.message;
 function modal(title){
  const dialog=el('dialog',undefined,'tag-dialog asset-dialog');dialog.setAttribute('aria-label',title);
  const header=el('header',undefined,'tag-header'),body=el('div',undefined,'tag-body'),footer=el('footer',undefined,'tag-footer');let busy=false;
  const close=()=>{if(busy)return;dialog.close();dialog.remove();};header.append(el('strong',title),button(t('close'),close));dialog.append(header,body,footer);document.body.append(dialog);dialog.addEventListener('cancel',e=>{e.preventDefault();close();});dialog.showModal();
  return {dialog,body,footer,close,setBusy:value=>{busy=value;dialog.querySelectorAll('button,input,select').forEach(n=>n.disabled=value);}};
 }
 function field(parent,label){const wrap=el('label',undefined,'tag-field'),input=el('input');input.maxLength=120;input.setAttribute('aria-label',label);wrap.append(el('span',label),input);parent.append(wrap);return input;}
 function status(parent){const n=el('p',undefined,'tag-status');n.setAttribute('role','status');parent.append(n);return n;}
 function openUpload(){
  const m=modal(t('upload'));m.body.append(el('p',t('uploadHint'),'tag-status'),el('p',t('uploadLimits'),'tag-status'));
  const input=el('input');input.type='file';input.accept='image/png,image/jpeg,image/webp';input.setAttribute('aria-label',t('uploadImage'));input.id='custom-upload-file';
  const preview=el('img',undefined,'asset-upload-preview');preview.alt=t('uploadPreview');preview.hidden=true;
  m.body.append(input,preview);const zh=field(m.body,t('customNameZh')),en=field(m.body,t('customNameEn'));m.body.append(el('p',t('nameHint'),'tag-status'));
  const types=new Set(),actions=new Set();
  m.body.append(el('h3',t('type')));tagTools.mountSelector(m.body,'type',types);
  const details=el('details');details.append(el('summary',t('action')));tagTools.mountSelector(details,'action',actions);m.body.append(details);
  const intensityLabel=el('label',undefined,'tag-field'),intensity=el('select');intensity.setAttribute('aria-label',t('intensity'));intensity.replaceChildren(...getData().taxonomy.tags.filter(v=>v.dimension==='intensity'&&!v.archived).map(v=>new Option(v[language()],v.id)));intensity.value='intensity_unrated';intensityLabel.append(el('span',t('intensity')),intensity);m.body.append(intensityLabel);
  const state=status(m.body);let file=null,url=null,ready=false;
  input.onchange=()=>{
   if(url)URL.revokeObjectURL(url);file=input.files[0]||null;ready=false;preview.hidden=true;state.textContent='';if(!file)return;
   if(file.size>20*1024*1024){state.textContent=t('file_too_large');return;}
   preview.onload=()=>{if(preview.naturalWidth*preview.naturalHeight>32000000){state.textContent=t('too_many_pixels');return;}ready=true;preview.hidden=false;};
   preview.onerror=()=>{state.textContent=t('invalid_image');};url=URL.createObjectURL(file);preview.src=url;
  };
  const close=m.close;m.close=()=>{if(url)URL.revokeObjectURL(url);close();};m.dialog.addEventListener('close',()=>{if(url)URL.revokeObjectURL(url);});
  const save=button(t('saveUpload'),async()=>{
   if(!file||!ready){state.textContent=t('image_required');return;}if(!zh.value.trim()&&!en.value.trim()){state.textContent=t('name_required');return;}
   m.setBusy(true);state.textContent=t('saving');
   try{
    const form=new FormData();form.append('image',file);form.append('metadata',JSON.stringify({name_zh:zh.value.trim(),name_en:en.value.trim(),type_ids:[...types],action_ids:[...actions],intensity_id:intensity.value,revision:getData().taxonomy.revision}));
    const result=await request('upload',form);await onSaved();m.setBusy(false);m.close();onUploaded(result.id);
   }catch(error){state.textContent=errorText(error);}finally{m.setBusy(false);}
  },'primary');m.footer.append(button(t('manage'),()=>tagTools.openManager()),button(t('cancel'),m.close),save);
 }
 function openName(row){
  const m=modal(t('renameCustom')),zh=field(m.body,t('customNameZh')),en=field(m.body,t('customNameEn'));zh.value=row.name_zh;en.value=row.name_en;const state=status(m.body);
  m.footer.append(button(t('cancel'),m.close),button(t('save'),async()=>{
   m.setBusy(true);try{await request('custom/name',{id:row.id,name_zh:zh.value,name_en:en.value,revision:getData().taxonomy.revision});await onSaved();m.setBusy(false);m.close();}catch(error){state.textContent=errorText(error);}finally{m.setBusy(false);}
  },'primary'));
 }
 async function openPlan(ids,mode='removed',revision=getData().taxonomy.revision,after=()=>{}){
  const m=modal(t('deleteTitle')),state=status(m.body);let plan;
  try{
   plan=await request('manage/plan',{ids,mode,revision});
   m.body.prepend(el('p',t('planSummary')(plan.items.length,plan.file_count,plan.release_bytes)),el('p',mode==='default'?t('restoreHint'):t('deleteHint'),'asset-delete-note'));
   const list=el('ul',undefined,'asset-plan-list');list.append(...plan.items.map(row=>el('li',`${name(row)} · ${row.id}`)));m.body.insertBefore(list,state);
  }catch(error){state.textContent=errorText(error);m.footer.append(button(t('close'),m.close));return;}
  m.footer.append(button(t('cancel'),m.close),button(t('confirmOperation'),async()=>{
   m.setBusy(true);state.textContent=t('saving');
   try{const result=await request('manage/apply',{request:plan.request,token:plan.token});await onSaved();state.textContent=t('resultSummary')(result.completed.length,result.failures.length);if(result.failures.length){state.textContent+='\n'+result.failures.map(v=>v.id+': '+(t(v.error)||v.error)).join('\n');}else{m.setBusy(false);m.close();}await after();}
   catch(error){state.textContent=errorText(error);}finally{m.setBusy(false);}
  },mode==='default'?'primary':'danger'));
 }
 function openManager(){
  const m=modal(t('manageAssets')),search=el('input'),list=el('div',undefined,'asset-manager-list'),selected=new Set();let records=[],revision=0;
  search.type='search';search.placeholder=t('managementSearch');search.setAttribute('aria-label',t('managementSearch'));
  const mode=el('select');mode.setAttribute('aria-label',t('operationMode'));mode.replaceChildren(...['removed','thumb_only','default'].map(key=>new Option(t('mode_'+key),key)));
  const heading=el('div',undefined,'tag-heading'),count=el('strong');heading.append(count,button(t('selectAllShown'),()=>{visible().forEach(row=>selected.add(row.id));render();}),button(t('clearSelection'),()=>{selected.clear();render();}));
  m.body.append(el('p',t('restoreHint'),'tag-status'),search,heading,mode,list);const state=status(m.body);
  const visible=()=>records.filter(row=>`${row.id} ${row.name_zh} ${row.name_en}`.toLowerCase().includes(search.value.trim().toLowerCase()));
  function render(){
   count.textContent=t('selectedCount')(selected.size);list.replaceChildren(...visible().map(row=>{
    const label=el('label',undefined,'asset-manager-row'),check=el('input');check.type='checkbox';check.checked=selected.has(row.id);check.setAttribute('aria-label',`${t('selectedBuiltin')} ${row.id}`);check.onchange=()=>{check.checked?selected.add(row.id):selected.delete(row.id);count.textContent=t('selectedCount')(selected.size);};
    const text=el('span');text.append(el('strong',row.id),el('small',`${t(row.management_state)} · ${(row.disk_bytes/1048576).toFixed(2)} MiB${!row.installed_original?' · '+t('originalMissing'):''}`));
    label.append(check);if(row.installed_thumb){const img=el('img');img.src=row.thumb_url;img.alt='';img.width=48;img.height=48;label.append(img);}label.append(text);return label;
   }));if(!visible().length)list.append(el('p',t('noResults'),'tag-status'));
  }
  async function load(){try{await onSaved();const result=await request('manage');records=result.records.filter(row=>row.origin==='builtin');revision=result.revision;render();}catch(error){state.textContent=errorText(error);}}
  m.footer.append(button(t('reload'),load),button(t('close'),m.close),button(t('previewOperation'),()=>{if(!selected.size){state.textContent=t('invalid_selection');return;}openPlan([...selected],mode.value,revision,load);},'primary'));
  search.oninput=render;load();
 }
 return {openUpload,openName,openPlan,openManager};
}
