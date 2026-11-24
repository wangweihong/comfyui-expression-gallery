import {app} from '../../scripts/app.js';
import {api} from '../../scripts/api.js';
import {strings,persist} from './i18n.mjs?v=0.3.1';

app.registerExtension({
 name:'comfyui-expression-gallery.browser',
 async beforeRegisterNodeDef(nodeType,nodeData){
  if(nodeData.name!=='ExpressionClayGallery')return;
  const created=nodeType.prototype.onNodeCreated;
  nodeType.prototype.onNodeCreated=function(){
   created?.apply(this,arguments);
   const node=this,widget=node.widgets.find(w=>w.name==='expression_id'),langWidget=node.widgets.find(w=>w.name==='language');
   let language=langWidget?.value==='en'?'en':'zh',dialog=null,frame=null,heading=null,done=null;
   const t=key=>strings[language][key];
   const toolbar=document.createElement('div');toolbar.style.cssText='display:flex;gap:7px;width:100%;height:42px;align-items:center;';
   const browse=document.createElement('button'),toggle=document.createElement('button');browse.type=toggle.type='button';
   browse.style.cssText='flex:1;min-width:0;height:36px;border:1px solid #b6c1aa;border-radius:6px;background:#e9ecdf;color:#30382e;cursor:pointer;font:12px sans-serif;';toggle.style.cssText='height:36px;width:65px;border:1px solid #b6c1aa;border-radius:6px;background:#fffef9;color:#30382e;cursor:pointer;font:12px sans-serif;';toolbar.append(browse,toggle);
   const preview=document.createElement('div');preview.style.cssText='width:100%;height:100%;min-height:280px;max-height:440px;position:relative;contain:size;border-radius:8px;background:#e5e5e2;overflow:hidden;cursor:pointer;';preview.setAttribute('role','button');preview.tabIndex=0;
   const image=document.createElement('img'),error=document.createElement('div');image.style.cssText='position:absolute;inset:0;width:100%;height:100%;object-fit:contain;';error.style.cssText='position:absolute;inset:15px;display:none;place-items:center;color:#71392e;font:13px/1.7 sans-serif;text-align:center;';error.setAttribute('role','status');preview.append(image,error);
   const update=(version='')=>{image.hidden=false;error.style.display='none';image.onload=()=>{image.hidden=false;error.style.display='none';};image.onerror=()=>{image.hidden=true;error.textContent=t('imageError')+' '+widget.value;error.style.display='grid';};const id=String(widget.value);image.src=api.apiURL(`/expression_gallery/assets/full/${encodeURIComponent(id)}${version?'?v='+encodeURIComponent(version):''}`);image.alt=String(widget.value);};
   const close=()=>{window.removeEventListener('message',receive);dialog?.remove();dialog=null;frame=null;heading=null;done=null;};
   const setLanguage=(value,notify=true)=>{
    language=value==='en'?'en':'zh';persist(language);if(langWidget)langWidget.value=language;
    browse.textContent=t('nodeBrowse');preview.setAttribute('aria-label',t('nodeBrowse'));preview.title=t('nodeBrowse');toggle.textContent=language==='en'?'中文':'English';widget.label=t('id');if(langWidget)langWidget.label=t('language');
    if(['ExpressionClayGallery','Expression Gallery','Expression Gallery 表情图库','Expression Gallery 白模表情图库','Expression Gallery · Clay'].includes(node.title))node.title=t('nodeTitle');
    node.outputs?.forEach((output,i)=>output.label=t('outputs')[i]||output.name);
    if(heading)heading.textContent=t('nodeBrowse');if(done)done.textContent=t('close');if(frame)frame.title=t('badge');if(error.style.display==='grid')error.textContent=t('imageError')+' '+widget.value;
    if(notify&&frame)frame.contentWindow.postMessage({type:'expression-gallery-language',language},location.origin);node.setDirtyCanvas(true,true);
   };
   const receive=event=>{
    if(event.origin!==location.origin||event.source!==frame?.contentWindow)return;
    if(event.data?.type==='expression-gallery-library-changed'){update(String(Date.now()));return;}
    if(event.data?.type==='expression-gallery-ready'){frame.contentWindow.postMessage({type:'expression-gallery-current',id:widget.value},location.origin);frame.contentWindow.postMessage({type:'expression-gallery-language',language},location.origin);}
    if(event.data?.type==='expression-gallery-language'&&['zh','en'].includes(event.data.language)){setLanguage(event.data.language,false);app.graph.change();}
    if(event.data?.type==='expression-gallery-select'&&typeof event.data.id==='string'&&/^(?:[FM](0[1-9]|[12][0-9]|3[0-5])(AF|AN|DI|HA|NE|SA|SU)|u-[a-f0-9]{32})$/.test(event.data.id)){
     widget.value=event.data.id;widget.callback?.(widget.value);node.setDirtyCanvas(true,true);app.graph.change();close();
    }
   };
   const callback=widget.callback;widget.callback=function(){callback?.apply(this,arguments);update();};
   if(langWidget){const callback=langWidget.callback;langWidget.callback=function(value){callback?.apply(this,arguments);setLanguage(value);app.graph.change();};}
   toggle.onclick=()=>{setLanguage(language==='en'?'zh':'en');app.graph.change();};
   const openGallery=()=>{
    if(dialog)return;dialog=document.createElement('dialog');dialog.style.cssText='width:96vw;height:94vh;max-width:1800px;max-height:96vh;padding:0;border:1px solid #c6c9bb;border-radius:12px;background:#f7f5f0;';
    const header=document.createElement('div');header.style.cssText='height:46px;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:0 18px;background:#e9ecdf;color:#30382e;font:13px sans-serif;';heading=document.createElement('strong');done=document.createElement('button');done.style.cssText='padding:5px 13px;border:1px solid #bdc5ae;background:#fff;color:#30382e;border-radius:5px;cursor:pointer;';done.onclick=close;header.append(heading,done);
    frame=document.createElement('iframe');frame.src=api.apiURL('/expression_gallery/gallery')+'?v=0.3.1&lang='+language;frame.style.cssText='width:100%;height:calc(100% - 46px);border:0;';dialog.append(header,frame);window.addEventListener('message',receive);dialog.addEventListener('cancel',event=>{event.preventDefault();close();});document.body.append(dialog);setLanguage(language,false);dialog.showModal();
   };
   browse.onclick=openGallery;preview.onclick=openGallery;preview.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();openGallery();}};
   node.addDOMWidget('expression_browser','expression_gallery_control',toolbar,{serialize:false,hideOnZoom:false,getMinHeight:()=>42,getMaxHeight:()=>42});
   node.addDOMWidget('expression_preview','expression_gallery_preview',preview,{serialize:false,hideOnZoom:false,getMinHeight:()=>280,getMaxHeight:()=>440});
   const configured=node.onConfigure;node.onConfigure=function(){configured?.apply(this,arguments);for(const name of ['expression_types_en','facial_actions_en','intensity_en','tags_json'])if(!node.outputs?.some(output=>output.name===name))node.addOutput?.(name,'STRING');setLanguage(langWidget?.value,false);update();};
   const removed=node.onRemoved;node.onRemoved=function(){close();removed?.apply(this,arguments);};
   node.setSize([420,490]);setLanguage(language,false);update();
  };
 }
});
