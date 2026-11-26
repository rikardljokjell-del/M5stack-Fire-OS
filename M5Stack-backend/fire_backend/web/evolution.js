/* App-scoped controls for the existing Builder/job/confirmation flow. */
let evolutionView=null,evolutionProject=null;
const evolutionLabels={generate:'Lag',repair:'Rett',optimize:'Optimaliser',expand:'Utvid',evolve:'Arbeidsmåte'};
async function showEvolution(project){
  evolutionProject=project;
  evolutionView=await api(`apps/${project}/evolution`);
  let dialog=document.querySelector('#evolution-dialog');
  if(!dialog){dialog=document.createElement('dialog');dialog.id='evolution-dialog';document.body.append(dialog)}
  const s=evolutionView,c=s.config,j=s.job;
  dialog.innerHTML=`<article class="panel"><div class="section-head"><h2>Evolution</h2><button data-evolution-close>Lukk</button></div>
    <p>${esc(j?.display_text||'Ingen aktiv jobb')} · Kostgrenser ${s.cost_enforcement?'på':'av'}</p>
    <p>Evolution ${cost(s.app_cost)} · I dag ${cost(s.daily_cost)}</p>
    <label><input id="evo-enabled" type="checkbox" ${c.enabled?'checked':''}> Aktiv for denne appen</label>
    <label><input id="evo-consent" type="checkbox" ${c.telemetry_consent?'checked':''}> Tillat kildebundet måletelemetri</label>
    <div class="actions">${Object.entries(evolutionLabels).map(([key,label])=>`<label><input data-evo-flag="${key}" type="checkbox" ${c.flags[key]?'checked':''}> ${label}</label>`).join('')}</div>
    <label>Selvstendighet<select id="evo-autonomy">${['manual','suggest','auto_build','assisted'].map(v=>`<option ${v===c.autonomy?'selected':''}>${v}</option>`).join('')}</select></label>
    <label>Nominelt mandatbudsjett USD<input id="evo-budget" type="number" min="0.01" step="0.01" value="${Number(c.limits.budget_usd)}"></label>
    <label>Ny brukerpreferanse<input id="evo-note" maxlength="160" placeholder="Valgfritt, lagres bare etter bekreftelse"></label>
    <button data-evolution-config>Forbered innstillinger</button>
    <label>Oppgave<select id="evo-operation">${Object.entries(evolutionLabels).map(([key,label])=>`<option value="${key}">${label}</option>`).join('')}</select></label>
    <label>Mål<input id="evo-goal" maxlength="1000"></label>
    <label>Målbar ressurs<select id="evo-metric">${['max_callback_display_work','app_memory_peak','max_io_calls','max_io_bytes'].map(v=>`<option>${v}</option>`).join('')}</select></label>
    <button data-evolution-prepare>Forbered oppgave</button>
    ${s.permission_request?'<button data-evolution-permissions>Vurder foreslåtte tillatelser</button>':''}
    <button data-evolution-compare>Vis sammenligning</button>
    <div class="actions">${[['pause','Pause'],['resume','Fortsett'],['stop','Stopp'],['revoke','Trekk mandat']].map(([key,label])=>`<button data-evolution-control="${key}">${label}</button>`).join('')}<button data-evolution-refresh>Oppdater</button></div>
    ${j?.state==='awaiting_build_confirm'?'<button data-evolution-open>Åpne vanlig byggforslag</button>':''}
    <p class="muted small">Installering og kjøring bekreftes alltid separat. PC-tester er ikke fysisk verifikasjon.</p>
    <pre>${esc(s.analysis?JSON.stringify(s.analysis,null,2):'')}</pre><div id="evolution-proposal"></div></article>`;
  if(!dialog.open)dialog.showModal();
}
document.addEventListener('click',async event=>{
  const b=event.target.closest('button');if(!b)return;
  try{
    if(b.dataset.evolution){await showEvolution(b.dataset.evolution);return}
    if(b.hasAttribute('data-evolution-close')){document.querySelector('#evolution-dialog').close();return}
    if(!evolutionView||!evolutionProject)return;
    const path=`apps/${evolutionProject}/evolution`;
    if(b.hasAttribute('data-evolution-refresh'))await showEvolution(evolutionProject);
    if(b.hasAttribute('data-evolution-compare')){const s=await api(path+'?view=compare');document.querySelector('#evolution-proposal').textContent=JSON.stringify(s.comparison||s.owner_comparison||s.analysis||'Ingen sammenligning ennå',null,2)}
    if(b.hasAttribute('data-evolution-permissions')){const r=evolutionView.permission_request;const p=await api(path+'/prepare','POST',{operation:r.operation,expected_revision:evolutionView.revision,value:r.prepare});evolutionView.proposal=p;document.querySelector('#evolution-proposal').innerHTML=`<h3>Vurder tillatelser</h3><pre>${esc(JSON.stringify(p,null,2))}</pre><button data-evolution-confirm>Bekreft</button>`}
    if(b.dataset.evolutionControl){await api(path+'/control','POST',{action:b.dataset.evolutionControl,expected_revision:evolutionView.revision,job_id:evolutionView.job?.id});await showEvolution(evolutionProject)}
    if(b.hasAttribute('data-evolution-config')||b.hasAttribute('data-evolution-prepare')){
      const configuration=b.hasAttribute('data-evolution-config');let value,operation;
      if(configuration){value=structuredClone(evolutionView.config);operation='configure';value.enabled=document.querySelector('#evo-enabled').checked;value.telemetry_consent=document.querySelector('#evo-consent').checked;value.autonomy=document.querySelector('#evo-autonomy').value;value.limits.budget_usd=Number(document.querySelector('#evo-budget').value);for(const e of document.querySelectorAll('[data-evo-flag]'))value.flags[e.dataset.evoFlag]=e.checked;const note=document.querySelector('#evo-note').value.trim();value.user_preferences=note?[note]:[]}
      else{operation=document.querySelector('#evo-operation').value;const app=state.data.apps.find(a=>a.project_id===evolutionProject&&a.package_id===(state.versions[evolutionProject]||state.data.apps.find(v=>v.project_id===evolutionProject)?.package_id));value={goal:document.querySelector('#evo-goal').value,base_package_id:app?.package_id,autonomy:document.querySelector('#evo-autonomy').value};if(['optimize','evolve'].includes(operation))value.metric=document.querySelector('#evo-metric').value}
      const proposal=await api(path+'/prepare','POST',{operation,expected_revision:evolutionView.revision,value});evolutionView.proposal=proposal;
      document.querySelector('#evolution-proposal').innerHTML=`<h3>Bekreft avgrenset valg</h3><pre>${esc(JSON.stringify(proposal,null,2))}</pre><button data-evolution-confirm>Bekreft</button>`;
    }
    if(b.hasAttribute('data-evolution-confirm')){const p=evolutionView.proposal;await api(path+'/confirm','POST',{proposal_id:p.id,expected_revision:p.expected_revision});await showEvolution(evolutionProject)}
    if(b.hasAttribute('data-evolution-open')){const s=await api(path+'/proposal');state.session=s.session_id;await poll();document.querySelector('#evolution-dialog').close();await show('dialog')}
  }catch(error){notice(error.message,true)}
});
