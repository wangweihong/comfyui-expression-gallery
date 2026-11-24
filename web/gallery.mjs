import {strings,preferred,persist} from './i18n.mjs?v=0.4.0';
import {createTagTools} from './tag_manager.mjs?v=0.4.0';
import {createAssetTools} from './asset_manager.mjs?v=0.4.0';
const $=id=>document.getElementById(id),PAGE=60;
let language=preferred(),data={records:[],taxonomy:{categories:[],tags:[],revision:0},meta:{}},category='',shown=0,filtered=[],current=0,selected='',signature='',batch=false;
const filterTags=new Set(),selectedImages=new Set();
const t=key=>strings[language][key],name=item=>item?.[language]||item?.en||'';
const activeCategories=()=>data.taxonomy.categories.filter(c=>!c.archived);
const activeTags=()=>data.taxonomy.tags.filter(tag=>!tag.archived&&(tag.dimension!=='type'||activeCategories().some(c=>c.id===tag.category_id)));
const tag=id=>data.taxonomy.tags.find(v=>v.id===id);
const label=row=>row.origin==='user'?(language==='en'?row.name_en:row.name_zh):(row.annotation.types.map(name).join(language==='en'?', ':'、')||t('unrated'));
const el=(type,text,cls)=>{const n=document.createElement(type);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const button=(text,fn,cls)=>{const n=el('button',text,cls);n.type='button';n.onclick=fn;return n;};
async function request(path,body){
 const multipart=body instanceof FormData;const response=await fetch(path,body===undefined?{cache:'no-store'}:{method:'POST',headers:multipart?{}:{'Content-Type':'application/json'},body:multipart?body:JSON.stringify(body)});
 const result=await response.json();if(!response.ok)throw new Error(result.error||`HTTP ${response.status}`);return result;
}
const tools=createTagTools({getData:()=>data,language:()=>language,t,request,onSaved:()=>refresh(true)});
const assets=createAssetTools({getData:()=>data,language:()=>language,t,request,tagTools:tools,onSaved:()=>refresh(true),onUploaded:id=>{
 category='';filterTags.clear();$('q').value='';$('actor').value='';$('origin').value='user';$('review-state').value='';filter();current=filtered.findIndex(row=>row.id===id);if(current>=0){detail();if(!$('viewer').open)$('viewer').showModal();}
}});
function renderCategories(){
 $('categories').replaceChildren(...[{id:'',count:data.records.length},...activeCategories()].map(c=>{
  const b=button(c.id?name(c):t('all'),()=>{category=c.id;for(const id of [...filterTags])if(tag(id)?.dimension==='type')filterTags.delete(id);filter();});
  b.dataset.category=c.id;b.setAttribute('aria-pressed',String(category===c.id));b.append(el('span',String(c.count)));return b;
 }));
 const types=activeTags().filter(tag=>tag.dimension==='type'&&tag.category_id===(category||'cat_basic'));
 $('type-options').replaceChildren(...types.map(item=>{
  const b=button('',()=>{filterTags.has(item.id)?filterTags.delete(item.id):filterTags.add(item.id);filter();},'tag-chip');b.dataset.tag=item.id;b.setAttribute('aria-pressed',String(filterTags.has(item.id)));b.append(el('span',name(item)),el('small',String(item.count)));return b;
 }));
 if(!types.length)$('type-options').append(el('p',t('emptyTypes')));
}
function renderControls(){
 const actor=$('actor').value,review=$('review-state').value,origin=$('origin').value;
 $('actor').replaceChildren(new Option(t('actor'),''),...[...new Set(data.records.map(r=>r.actor))].sort().map(a=>new Option(a==='custom'?t('customActor'):a,a)));$('actor').value=actor;
 $('origin').replaceChildren(new Option(t('allOrigins'),''),new Option(t('builtin'),'builtin'),new Option(t('user'),'user'));$('origin').value=origin;
 $('review-state').replaceChildren(new Option(t('reviewFilter'),''),new Option(t('unreviewed'),'unreviewed'),new Option(t('reviewed'),'reviewed'));$('review-state').value=review;
 $('total').textContent=t('progress')(data.records.length,data.meta.total??490);
 $('batch-state').textContent=t('overview')(activeCategories().length,activeTags().filter(tag=>tag.dimension==='type').length,data.meta.actors||0);
}
function renderFilters(){
 $('filter-tags').replaceChildren(...[...filterTags].map(id=>button(`${name(tag(id))} ×`,()=>{filterTags.delete(id);filter();},'tag-chip selected')));$('clear-tag-filters').hidden=!filterTags.size;
}
function searchText(row){
 const items=[...row.annotation.types,...row.annotation.actions,row.annotation.intensity];
 const cats=data.taxonomy.categories.filter(c=>row.category_ids.includes(c.id));
 return `${row.id} ${row.actor} ${row.name_zh||''} ${row.name_en||''} ${row.original_filename||''} ${row.filename} ${items.concat(cats).map(v=>`${v.zh} ${v.en} ${(v.aliases||[]).join(' ')}`).join(' ')}`.toLowerCase();
}
function filter(){
 const words=$('q').value.toLowerCase().trim().split(/\s+/).filter(Boolean),actor=$('actor').value,review=$('review-state').value,origin=$('origin').value;
 filtered=data.records.filter(row=>(!category||row.category_ids.includes(category))&&(!origin||row.origin===origin)&&(!actor||row.actor===actor)&&(!review||row.reviewed===(review==='reviewed'))&&[...filterTags].every(id=>[...row.type_ids,...row.action_ids,row.intensity_id].includes(id))&&words.every(w=>searchText(row).includes(w)));
 shown=0;$('grid').replaceChildren();renderCategories();renderFilters();$('section-title').textContent=category?name(data.taxonomy.categories.find(c=>c.id===category)):t('all');
 $('empty').textContent=category&&!data.taxonomy.categories.find(c=>c.id===category)?.count&&!words.length&&!filterTags.size?t('noMaterials'):t('empty');$('empty').hidden=filtered.length!==0;appendPage();renderBatch();
}
function renderBatch(){
 $('batch-toolbar').hidden=!batch;$('batch-toggle').textContent=t(batch?'exitBatch':'batch');$('selected-count').textContent=t('selectedCount')(selectedImages.size);$('batch-edit').disabled=!selectedImages.size;$('batch-delete').disabled=!selectedImages.size;
 document.querySelectorAll('.card-select').forEach(label=>{label.hidden=!batch;label.querySelector('input').checked=selectedImages.has(label.dataset.id);});
}
function appendPage(){
 const start=shown,cards=filtered.slice(start,start+PAGE).map((row,i)=>{
  const wrap=el('div',undefined,'card-wrap'),card=button('',()=>{current=start+i;detail();$('viewer').showModal();},'card');card.dataset.id=row.id;card.setAttribute('aria-current',String(row.id===selected));card.setAttribute('aria-label',`${label(row)} ${row.id}`);
  const image=el('img');image.src=row.thumb_url;image.alt=`${label(row)} · ${row.id}`;image.width=256;image.height=256;image.loading='lazy';image.decoding='async';image.onerror=()=>{image.alt=t('imageError')+' '+row.id;};
  const info=el('div',undefined,'card-info'),heading=el('div',undefined,'card-heading');heading.append(el('strong',row.origin==='user'?label(row):row.id,'asset-name'),el('span',row.origin==='user'?t('user'):label(row)));info.append(heading,el('p',`${row.annotation.types.map(v=>v.en).join(', ')||(row.origin==='user'?row.name_en:t('noTags'))} · ${row.width} × ${row.height}`),el('p',`${name(row.annotation.intensity)} · ${t(row.reviewed?'reviewed':'unreviewed')}`,'annotation-badge'));card.append(image,info);
  const checkbox=el('label',undefined,'card-select');checkbox.dataset.id=row.id;checkbox.hidden=!batch;const input=el('input');input.type='checkbox';input.setAttribute('aria-label',`${t('chosen')} ${row.id}`);input.onchange=()=>{input.checked?selectedImages.add(row.id):selectedImages.delete(row.id);renderBatch();};checkbox.append(input);wrap.append(card,checkbox);return wrap;
 });
 $('grid').append(...cards);shown+=cards.length;$('status').textContent=t('status')(filtered.length,shown);$('more').hidden=shown>=filtered.length;renderBatch();
}
function detail(){
 const row=filtered[current];if(!row)return;
 $('detail-title').textContent=label(row);$('detail-code').textContent=row.id;$('detail-label').textContent=row.annotation.types.map(v=>`${v.en} · ${v.zh}`).join(' / ');
 $('detail-meta').textContent=`${row.actor} · ${row.width} × ${row.height} · PNG`;$('position').textContent=`${current+1} / ${filtered.length}`;
 $('detail-tags').replaceChildren(...['type','action','intensity'].map(dimension=>{
  const block=el('div');block.append(el('h3',t(dimension)));const cloud=el('div',undefined,'tag-summary'),items=dimension==='type'?row.annotation.types:dimension==='action'?row.annotation.actions:[row.annotation.intensity];
  cloud.append(...(items.length?items.map(v=>el('span',name(v),'tag-chip')):[el('small',t('unrated'))]));block.append(cloud);return block;
 }));
 const im=$('large');im.onload=()=>{$('image-status').textContent=row.original_available?'':t('missingOriginal');};im.onerror=()=>{$('image-status').textContent=t('imageError');};const imageUrl=row.original_available?row.image_url:row.thumb_url;if(!im.src.endsWith(imageUrl))im.src=imageUrl;im.alt=`${label(row)} ${row.id}`;
 for(const id of ['download','open']){const link=$(id);link.setAttribute('aria-disabled',String(!row.original_available));if(row.original_available)link.href=row.image_url;else link.removeAttribute('href');}$('download').download=row.filename;
 $('rename-custom').hidden=row.origin!=='user';
 if(!row.original_available)$('image-status').textContent=t('missingOriginal');$('prev').disabled=current===0;$('next').disabled=current===filtered.length-1;$('copy').textContent=t('copy');
 $('use').disabled=window.parent===window||!row.original_available;$('use').textContent=t(!row.original_available?'missingOriginal':window.parent===window?'standalone':'use');
}
function setLanguage(value,notify=true){
 const active=$('viewer').open?filtered[current]?.id:null;
 language=value==='en'?'en':'zh';persist(language);document.documentElement.lang=language==='en'?'en':'zh-CN';document.title=language==='en'?'Expression Gallery · White-clay References':'表情图库 · 白模参考';
 document.querySelectorAll('[data-t]').forEach(n=>n.textContent=t(n.dataset.t));$('language').textContent=language==='en'?'中文':'English';$('q').placeholder=t('search');$('q').setAttribute('aria-label',t('search'));
 renderControls();filter();if(active){current=filtered.findIndex(r=>r.id===active);if(current>=0)detail();else $('viewer').close();}
 if(notify&&parent!==window)parent.postMessage({type:'expression-gallery-language',language},location.origin);
}
async function refresh(force=false){
 try{
  const response=await fetch('catalog',{cache:'no-store'});if(!response.ok)throw new Error(`HTTP ${response.status}`);const next=await response.json();$('load-error').hidden=true;$('retry').hidden=true;const nextSignature=`${next.taxonomy.revision}:${next.records.length}`;
  if(force||signature!==nextSignature){signature=nextSignature;data=next;if(!activeCategories().some(c=>c.id===category))category='';const valid=new Set(activeTags().map(t=>t.id));for(const id of [...filterTags])if(!valid.has(id))filterTags.delete(id);const existing=new Set(data.records.map(r=>r.id));for(const id of [...selectedImages])if(!existing.has(id))selectedImages.delete(id);setLanguage(language,false);if(parent!==window)parent.postMessage({type:'expression-gallery-library-changed'},location.origin);}
 }catch(error){$('load-error').textContent=t('error')+` (${error.message})`;$('load-error').hidden=false;$('retry').hidden=false;if(force)throw error;}
}
$('q').oninput=filter;$('origin').onchange=filter;$('actor').onchange=filter;$('review-state').onchange=filter;
$('reset').onclick=()=>{category='';filterTags.clear();$('q').value='';$('actor').value='';$('origin').value='';$('review-state').value='';filter();};
$('custom-upload-open').onclick=()=>assets.openUpload();$('manage-assets').onclick=()=>assets.openManager();$('delete-image').onclick=()=>assets.openPlan([filtered[current].id]);$('rename-custom').onclick=()=>assets.openName(filtered[current]);$('batch-delete').onclick=()=>assets.openPlan([...selectedImages]);
$('more').onclick=appendPage;$('retry').onclick=()=>refresh();$('language').onclick=()=>setLanguage(language==='en'?'zh':'en');$('manage-tags').onclick=()=>tools.openManager();
$('tag-filter').onclick=()=>tools.openFilter([...filterTags],ids=>{filterTags.clear();const valid=new Set(activeTags().map(t=>t.id));ids.filter(id=>valid.has(id)).forEach(id=>filterTags.add(id));filter();});
$('clear-tag-filters').onclick=()=>{filterTags.clear();filter();};$('batch-toggle').onclick=()=>{batch=!batch;renderBatch();};$('select-page').onclick=()=>{filtered.slice(0,shown).forEach(r=>selectedImages.add(r.id));renderBatch();};$('select-filtered').onclick=()=>{filtered.forEach(r=>selectedImages.add(r.id));renderBatch();};$('clear-selection').onclick=()=>{selectedImages.clear();renderBatch();};
$('batch-edit').onclick=()=>tools.openEditor([...selectedImages],true);$('edit-tags').onclick=()=>tools.openEditor([filtered[current].id]);$('guide-toggle').onclick=()=>$('guide').showModal();$('close').onclick=()=>$('viewer').close();$('prev').onclick=()=>{if(current>0){current--;detail();}};$('next').onclick=()=>{if(current<filtered.length-1){current++;detail();}};
$('copy').onclick=async()=>{try{await navigator.clipboard.writeText(filtered[current].id);$('copy').textContent=t('copied');}catch{$('copy').textContent=t('copyError');}};$('use').onclick=()=>{if(parent!==window)parent.postMessage({type:'expression-gallery-select',id:filtered[current].id},location.origin);};
for(const id of ['viewer','guide'])$(id).addEventListener('click',event=>{if(event.target===$(id)){const r=$(id).getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)$(id).close();}});
document.addEventListener('keydown',event=>{if(document.querySelector('.tag-dialog[open]'))return;if($('viewer').open){if(event.key==='ArrowLeft')$('prev').click();if(event.key==='ArrowRight')$('next').click();}else if(event.key==='/'&&!['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName)){event.preventDefault();$('q').focus();}});
window.addEventListener('message',event=>{if(event.origin!==location.origin||event.source!==parent||parent===window)return;if(event.data?.type==='expression-gallery-language'&&['zh','en'].includes(event.data.language))setLanguage(event.data.language,false);if(event.data?.type==='expression-gallery-current'&&typeof event.data.id==='string'){selected=event.data.id;document.querySelectorAll('.card').forEach(c=>c.setAttribute('aria-current',String(c.dataset.id===selected)));current=filtered.findIndex(row=>row.id===selected);if(current>=0){detail();if(!$('viewer').open)$('viewer').showModal();}}});
setLanguage(language,false);$('status').textContent=t('loading');await refresh();if(parent!==window)parent.postMessage({type:'expression-gallery-ready'},location.origin);setInterval(()=>{if(!document.hidden&&!document.querySelector('.tag-dialog[open]'))refresh();},15000);
