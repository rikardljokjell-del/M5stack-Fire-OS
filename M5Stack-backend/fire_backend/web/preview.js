'use strict';
// Local, bounded replay in the existing sandbox. No physical device actions.
let previewTarget='',previewButtons=[],previewElapsed=1000,previewImages=[],previewRequest=0,previewBusy=false;
let previewApiVersion='';
const previewDialog=document.querySelector('#app-preview');
function previewFrame(index){
  const frame=previewImages[index];if(!frame)return;
  document.querySelector('#preview-image').src=frame.image_url;
  document.querySelector('#preview-image').hidden=false;
  document.querySelector('#preview-frame').textContent=`${index+1} / ${previewImages.length} · ${(frame.at_ms/1000).toFixed(2)} s`;
  document.querySelector('#preview-slider').value=index;
}
async function refreshPreview(){
  if(!previewTarget||previewBusy)return;
  const request=++previewRequest,target=previewTarget;
  previewBusy=true;previewDialog.querySelectorAll('[data-preview-input],#preview-reset,#preview-advance').forEach(b=>b.disabled=true);
  document.querySelector('#preview-state').textContent='Beregner forhåndsvisning…';
  try{
    const result=await api('packages/'+encodeURIComponent(target)+'/preview','POST',{buttons:previewButtons,elapsed_ms:previewElapsed});
    if(request!==previewRequest||target!==previewTarget)return;
    previewImages=result.images;
    const slider=document.querySelector('#preview-slider');slider.max=Math.max(0,previewImages.length-1);slider.disabled=previewImages.length<2;
    previewFrame(previewImages.length-1);
    document.querySelector('#preview-state').textContent=previewImages.length?'PC-simulering · ingen app kjører på FIRE':'Ingen skjermbilder i denne simuleringen.';
    document.querySelector('#preview-inputs').textContent=previewButtons.length?'Korttrykk: '+previewButtons.join(' → '):'Ingen knappetrykk';
    const legacy=!previewApiVersion.startsWith('fire-app-sdk-')||previewImages.some(f=>f.metrics?.font_data_exact===false);
    document.querySelector('#preview-parity').textContent=legacy?'Legacyfont er en referanse; firmwareinnstillinger og fysisk grafikk er ikke verifisert.':'Felles SDK-bitmapfontdata. Native timing og fysisk grafikk er ikke verifisert.';
  }catch(error){if(request===previewRequest)document.querySelector('#preview-state').textContent=error.message;}
  finally{if(request===previewRequest){previewBusy=false;previewDialog.querySelectorAll('[data-preview-input],#preview-reset,#preview-advance').forEach(b=>b.disabled=false);}}
}
document.addEventListener('click',async event=>{
  const b=event.target.closest('button');if(!b)return;
  if(b.dataset.preview){
    ++previewRequest;previewBusy=false;previewTarget=b.dataset.preview;previewButtons=[];previewElapsed=1000;previewImages=[];
    previewApiVersion=state.data?.apps?.find(a=>a.package_id===previewTarget)?.api_version||'';
    document.querySelector('#preview-image').hidden=true;previewDialog.showModal();await refreshPreview();return;
  }
  if(b.id==='preview-close'){previewTarget='';++previewRequest;previewBusy=false;previewDialog.close();return;}
  if(b.dataset.previewInput){if(previewButtons.length>=32){document.querySelector('#preview-state').textContent='32 korttrykk er nådd. Velg Ny start for en ny simulering.';return;}previewButtons.push(b.dataset.previewInput);await refreshPreview();}
  if(b.id==='preview-reset'){previewButtons=[];previewElapsed=1000;await refreshPreview();}
  if(b.id==='preview-advance'){previewElapsed=Math.min(12000,previewElapsed+1000);await refreshPreview();}
});
document.querySelector('#preview-slider').addEventListener('input',event=>previewFrame(Number(event.target.value)));
previewDialog.addEventListener('cancel',()=>{previewTarget='';++previewRequest;previewBusy=false;});
