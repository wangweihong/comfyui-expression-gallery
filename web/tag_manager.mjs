// Search, selected chips, usage counts, and a separate manager follow the prompt-library picker.
export function createTagTools({getData,language,t,request,onSaved}){
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const name=item=>item[language()]||item.en;
 const button=(text,fn,cls)=>{const n=el('button',text,cls);n.type='button';n.onclick=fn;return n;};
 const activeTags=()=>getData().taxonomy.tags.filter(tag=>!tag.archived&&(tag.dimension!=='type'||getData().taxonomy.categories.some(c=>c.id===tag.category_id&&!c.archived)));
 const matches=(item,q)=>`${item.zh} ${item.en} ${(item.aliases||[]).join(' ')}`.toLowerCase().includes(q.trim().toLowerCase());
 function modal(title){
  const dialog=el('dialog',undefined,'tag-dialog');dialog.setAttribute('aria-label',title);
  const header=el('header',undefined,'tag-header'),body=el('div',undefined,'tag-body'),footer=el('footer',undefined,'tag-footer');
  const close=()=>{dialog.close();dialog.remove();};header.append(el('strong',title),button(t('close'),close));dialog.append(header,body,footer);document.body.append(dialog);
  dialog.addEventListener('cancel',event=>{event.preventDefault();close();});dialog.showModal();return {dialog,body,footer,close};
 }
 function status(parent){const n=el('p',undefined,'tag-status');n.setAttribute('role','status');parent.append(n);return n;}
 function field(parent,label,kind='input'){
  const wrap=el('label',undefined,'tag-field'),input=el(kind);input.setAttribute('aria-label',label);wrap.append(el('span',label),input);parent.append(wrap);return input;
 }
 function selector(parent,dimension,selected,{onChange=()=>{},category='',single=false}={}){
  const shell=el('section',undefined,'tag-selector');shell.dataset.dimension=dimension;
  const search=el('input');search.type='search';search.placeholder=t('tagSearch');search.setAttribute('aria-label',`${t(dimension)} · ${t('tagSearch')}`);
  const chosen=el('div',undefined,'tag-chosen'),options=el('div',undefined,'tag-cloud');options.setAttribute('aria-label',t(dimension));
  const heading=el('div',undefined,'tag-heading');heading.append(el('strong',t('chosen')),button(t('clearChosen'),()=>{selected.clear();render();onChange();}));
  shell.append(search,heading,chosen,options);parent.append(shell);
  function render(){
   const tags=activeTags().filter(tag=>tag.dimension===dimension);
   chosen.replaceChildren(...[...selected].map(id=>{const tag=getData().taxonomy.tags.find(v=>v.id===id);return button(`${tag?name(tag):id} ×`,()=>{selected.delete(id);render();onChange();},'tag-chip selected');}));
   const found=tags.filter(tag=>(!category||tag.category_id===category)&&matches(tag,search.value));
   options.replaceChildren(...found.map(tag=>{const b=button('',()=>{if(selected.has(tag.id))selected.delete(tag.id);else{if(single)selected.clear();selected.add(tag.id);}render();onChange();},'tag-chip');b.dataset.tag=tag.id;b.setAttribute('aria-pressed',String(selected.has(tag.id)));b.append(el('span',name(tag)),el('small',String(tag.count)));return b;}));
   if(!found.length)options.append(el('p',t('noResults'),'tag-status'));
  }
  search.oninput=render;render();return {shell,render};
 }
 function openFilter(value,onApply){
  const m=modal(t('filters')),selected=new Set(value),tabs=el('div',undefined,'tag-tabs'),content=el('div');let dimension='type';
  function render(){
   tabs.replaceChildren(...['type','action','intensity'].map(key=>{const b=button(t(key),()=>{dimension=key;render();});b.setAttribute('aria-pressed',String(dimension===key));return b;}));
   content.replaceChildren();const local=new Set([...selected].filter(id=>getData().taxonomy.tags.find(v=>v.id===id)?.dimension===dimension));
   selector(content,dimension,local,{onChange:()=>{for(const id of [...selected])if(getData().taxonomy.tags.find(v=>v.id===id)?.dimension===dimension)selected.delete(id);for(const id of local)selected.add(id);},single:dimension==='intensity'});
  }
  m.body.append(el('p',t('annotationHint'),'tag-status'),tabs,content);m.footer.append(button(t('manage'),()=>openManager()),button(t('cancel'),m.close),button(t('apply'),()=>{onApply([...selected]);m.close();},'primary'));render();
 }
 function openEditor(ids,batch=false){
  const data=getData(),row=data.records.find(r=>r.id===ids[0]);if(!row)return;
  const m=modal(batch?`${t('batchEdit')} · ${ids.length}`:`${t('annotationEditor')} · ${row.id}`),revision=data.taxonomy.revision;
  m.body.append(el('p',batch?t('batchHint'):t('annotationHint'),'tag-status'));
  const mode=batch?field(m.body,t('mode'),'select'):null;
  if(mode)mode.replaceChildren(...['add','replace','remove'].map(key=>new Option(t(key),key)));
  const changes={},selected={type:new Set(batch?[]:row.type_ids),action:new Set(batch?[]:row.action_ids),intensity:new Set(batch?[]:[row.intensity_id])};
  for(const dimension of ['type','action','intensity']){
   const group=el('section',undefined,'annotation-group'),head=el('div',undefined,'tag-heading');head.append(el('h3',t(dimension)));
   const enabled=el('input');enabled.type='checkbox';enabled.checked=!batch;enabled.setAttribute('aria-label',`${t('changeField')} ${t(dimension)}`);changes[dimension]=enabled;
   if(batch){const label=el('label',undefined,'inline-check');label.append(enabled,el('span',t('changeField')));head.append(label);}
   group.append(head);const picker=selector(group,dimension,selected[dimension],{single:dimension==='intensity',onChange:()=>{enabled.checked=true;picker.shell.inert=false;picker.shell.classList.remove('muted');}});
   // Leave pickers usable: choosing a tag checks its dimension automatically.
   m.body.append(group);
  }
  const state=status(m.body),save=button(t('save'),async()=>{
   const body={revision,ids,mode:mode?.value||'replace'};
   if(changes.type.checked)body.type_ids=[...selected.type];if(changes.action.checked)body.action_ids=[...selected.action];
   if(changes.intensity.checked)body.intensity_id=[...selected.intensity][0]||'intensity_unrated';
   save.disabled=true;state.textContent=t('saving');
   try{await request('annotations',body);await onSaved();m.close();}catch(error){state.textContent=error.message;}finally{save.disabled=false;}
  },'primary');
  m.footer.append(button(t('reload'),async()=>{await onSaved();m.close();openEditor(ids,batch);}),button(t('cancel'),m.close),save);
 }
 function openManager(){
  const m=modal(t('manage')),tabs=el('div',undefined,'tag-tabs'),search=el('input'),list=el('div',undefined,'tag-manager-list');let dimension='category',busy=false;
  search.type='search';search.placeholder=t('tagSearch');search.setAttribute('aria-label',t('tagSearch'));
  const archivedLabel=el('label',undefined,'inline-check'),archived=el('input');archived.type='checkbox';archivedLabel.append(archived,el('span',t('showArchived')));
  const tools=el('div',undefined,'tag-heading'),add=button(t('newItem'),()=>editItem(null));tools.append(add,archivedLabel);
  const state=status(m.body);m.body.append(el('p',t('managerHint'),'tag-status'),tabs,search,tools,list);
  async function reload(){await onSaved();render();}
  function render(){
   tabs.replaceChildren(...['category','type','action','intensity'].map(key=>{const b=button(t(key),()=>{dimension=key;render();});b.setAttribute('aria-pressed',String(dimension===key));b.disabled=busy;return b;}));
   const data=getData().taxonomy,items=(dimension==='category'?data.categories:data.tags.filter(tag=>tag.dimension===dimension)).filter(item=>(archived.checked||!item.archived)&&matches(item,search.value));
   list.replaceChildren(...items.map(item=>{
    const row=el('div',undefined,'tag-manager-row');row.dataset.id=item.id;
    const text=el('div');text.append(el('strong',name(item)),el('small',`${item.en} · ${t('countImages')(item.linked_count??item.count)}${item.archived?' · '+t('archived'):''}`));
    const actions=el('div',undefined,'tag-row-actions');row.append(text,actions);
    if(item.id==='intensity_unrated'){actions.append(el('span',t('reserved'),'tag-status'));return row;}
    const edit=button(t('edit'),()=>editItem(item));edit.disabled=busy;actions.append(edit);
    const remove=button(t(item.archived?'restore':'archive'),async()=>{
     if(item.archived){await mutate('restore',item);return;}
     const confirmation=modal(t('archiveTitle'));confirmation.body.append(el('p',t('archiveText')(name(item),item.linked_count??item.count)));
     confirmation.footer.append(button(t('cancel'),confirmation.close),button(t('archive'),async()=>{confirmation.close();await mutate('archive',item);},'danger'));
    });remove.disabled=busy;actions.append(remove);return row;
   }));
   if(!items.length)list.append(el('p',t('noResults'),'tag-status'));add.disabled=busy;
  }
  async function mutate(operation,item){
   busy=true;render();state.textContent=t('saving');
   try{await request('taxonomy',{entity:dimension==='category'?'category':'tag',operation,id:item.id,revision:getData().taxonomy.revision});await reload();state.textContent=t('saved');}catch(error){state.textContent=error.message;}finally{busy=false;render();}
  }
  function editItem(item){
   const revision=getData().taxonomy.revision,form=modal(t(item?'editTitle':'createTitle'));
   const zh=field(form.body,t('nameZh')),en=field(form.body,t('nameEn')),aliases=field(form.body,t('aliases'));
   zh.maxLength=en.maxLength=100;zh.value=item?.zh||'';en.value=item?.en||'';aliases.value=(item?.aliases||[]).join(', ');
   let category;
   if(dimension==='type'){category=field(form.body,t('parentCategory'),'select');category.replaceChildren(...getData().taxonomy.categories.filter(c=>!c.archived).map(c=>new Option(name(c),c.id)));category.value=item?.category_id||category.options[0]?.value||'';}
   const state=status(form.body),save=button(t('save'),async()=>{
    save.disabled=true;state.textContent=t('saving');
    try{await request('taxonomy',{entity:dimension==='category'?'category':'tag',operation:item?'update':'create',id:item?.id,revision,dimension,category_id:category?.value,zh:zh.value,en:en.value,aliases:aliases.value.split(/[,，]/).map(s=>s.trim()).filter(Boolean)});await reload();form.close();}catch(error){state.textContent=error.message;}finally{save.disabled=false;}
   },'primary');form.footer.append(button(t('cancel'),form.close),save);zh.focus();
  }
  search.oninput=render;archived.onchange=render;m.footer.append(button(t('reload'),reload),button(t('close'),m.close));render();
 }
 return {openFilter,openEditor,openManager,mountSelector:selector};
}
