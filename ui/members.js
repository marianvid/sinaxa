document.documentElement.dataset.theme=localStorage.getItem('sinaxa-theme')||'dark';
const $=x=>document.getElementById(x),esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
let S={};
async function api(path,o={}){let r=await fetch(path,{headers:{'Content-Type':'application/json'},...o}),b=await r.json();if(!r.ok)throw Error(b.error);return b}
const engines=()=>S.engines.filter(x=>x.enabled);
async function load(){
  S=await api('/api/state');
  $('list').innerHTML=S.members.map(m=>`<article class="card" data-id="${m.id}"><h2>${esc(m.name)}</h2><p>${m.kind==='human'?'Human lead':esc(S.engines.find(e=>e.id===m.engine)?.name||m.engine)}</p><div class="tags">${m.model?`<span>${esc(m.model)}</span>`:''}${m.effort?`<span>${esc(m.effort)}</span>`:''}</div></article>`).join('')||'<p>No members yet.</p>';
  document.querySelectorAll('[data-id]').forEach(n=>n.onclick=()=>edit(S.members.find(m=>m.id===n.dataset.id)));
}
function fields(m={}){return `<label>Name<input name="name" value="${esc(m.name)}" required></label><label>Kind<select name="kind"><option value="agent">Agent</option><option value="human" ${m.kind==='human'?'selected':''}>Human lead</option></select></label><label>Engine<select name="engine"><option value="">—</option>${engines().map(e=>`<option value="${e.id}" ${m.engine===e.id?'selected':''}>${esc(e.name)}</option>`).join('')}</select></label><label>Model<input name="model" value="${esc(m.model)}" placeholder="Engine default"></label><label>Effort<input name="effort" value="${esc(m.effort)}" placeholder="Engine default"></label>${m.id&&m.kind!=='human'?'<label class="danger"><input type="checkbox" name="remove"> Remove member</label>':''}`}
function edit(m){
  $('title').textContent=m?'Edit member':'New member';$('fields').innerHTML=fields(m);let d=$('dialog');d.showModal();
  d.onclose=async()=>{if(d.returnValue!=='default')return;let f=new FormData(d.querySelector('form'));try{if(f.get('remove'))await api('/api/members/'+m.id,{method:'DELETE'});else{let v={name:f.get('name'),kind:f.get('kind'),engine:f.get('engine')||null,model:f.get('model')||null,effort:f.get('effort')||null};await api('/api/members'+(m?'/'+m.id:''),{method:m?'PATCH':'POST',body:JSON.stringify(v)})}load()}catch(e){alert(e.message)}};
}
document.addEventListener('click',e=>{if(e.target.matches('dialog button[value="cancel"]')){e.preventDefault();e.target.closest('dialog').close('cancel')}});
$('add').onclick=()=>edit();load();
