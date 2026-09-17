document.documentElement.dataset.theme=localStorage.getItem('sinaxa-theme')||'dark';
const $=x=>document.getElementById(x),esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
let S={};
async function api(path,o={}){let r=await fetch(path,{headers:{'Content-Type':'application/json'},...o}),b=await r.json();if(!r.ok)throw Error(b.error);return b}
async function load(){
  S=await api('/api/state');
  $('list').innerHTML=S.engines.map(e=>`<article class="engine" data-id="${e.id}"><div><h2>${esc(e.name)}</h2><div class="tags"><span>${esc(e.kind)}</span><span>${esc(e.mode)}</span><span>${e.max_concurrency} concurrent</span><span>${e.streaming?'streaming':'buffered'}</span></div></div><b class="${e.enabled?'enabled':'disabled'}">${e.enabled?'Enabled':'Disabled'}</b></article>`).join('');
  document.querySelectorAll('[data-id]').forEach(n=>n.onclick=()=>edit(S.engines.find(e=>e.id===n.dataset.id)));
}
function edit(e){
  $('title').textContent=e.name;
  $('fields').innerHTML=`<label class="inline"><input type="checkbox" name="enabled" ${e.enabled?'checked':''}> Enabled</label><label>Display name<input name="name" value="${esc(e.name)}"></label><label>Executable path<input name="executable" value="${esc(e.executable)}"></label><label>Conversation mode<select name="mode"><option value="persistent" selected>Persistent process / streaming context</option><option value="resume" disabled>Non-persistent / resume each turn — Not yet implemented</option></select><small>Only persistent project agents are currently available. Non-persistent mode is retained for future implementation.</small></label><label class="inline"><input type="checkbox" name="streaming" ${e.streaming?'checked':''}> Enable streamed transport when supported</label><label>Maximum simultaneous turns<input type="number" name="max_concurrency" min="1" value="${e.max_concurrency}"></label><label>MCP servers <small>(one name per line; members may later allow a subset)</small><textarea name="mcp_servers">${esc((e.mcp_servers||[]).join('\n'))}</textarea></label>${e.kind==='opencode'?`<label>Base port<input name="base_port" type="number" value="${e.options?.base_port||4096}"></label>`:''}`;
  let d=$('dialog');d.showModal();d.onclose=async()=>{if(d.returnValue!=='default')return;let f=new FormData(d.querySelector('form')),options={...(e.options||{})};if(e.kind==='opencode')options.base_port=+f.get('base_port');try{await api('/api/engines/'+e.id,{method:'PATCH',body:JSON.stringify({enabled:!!f.get('enabled'),name:f.get('name'),executable:f.get('executable'),mode:f.get('mode'),streaming:!!f.get('streaming'),max_concurrency:+f.get('max_concurrency'),mcp_servers:String(f.get('mcp_servers')).split('\n').map(x=>x.trim()).filter(Boolean),options})});load()}catch(x){alert(x.message)}};
}
document.addEventListener('click',e=>{if(e.target.matches('dialog button[value="cancel"]')){e.preventDefault();e.target.closest('dialog').close('cancel')}});
load();
