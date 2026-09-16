const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, character => (
  {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]
));
let state = {};
async function api(path, options={}) { const response=await fetch(path,{headers:{'Content-Type':'application/json'},...options}); const data=await response.json().catch(()=>({})); if(!response.ok) throw new Error(data.error||response.statusText); return data; }

function fields(type={}) {
  const selected = new Set(type.seat_templates || []);
  return `<label>Name<input name="name" value="${esc(type.name)}" required></label>
    <label>Category<select name="category">${['general','software','editorial','creative','media'].map(category => `<option value="${category}" ${type.category===category?'selected':''}>${category}</option>`).join('')}</select></label>
    <label>Description<textarea name="description" rows="3">${esc(type.description)}</textarea></label>
    <div class="field">Default seats<div class="template-list">${(state.seat_templates || []).map(item => `<label class="choice"><input type="checkbox" name="seat_templates" value="${item.id}" ${selected.has(item.id)?'checked':''}> ${esc(item.role)} <small>· ${esc(item.category)}</small></label>`).join('') || 'Create seat templates first.'}</div></div>
    ${type.id ? '<label class="danger"><input type="checkbox" name="remove"> Remove project type</label>' : ''}`;
}

function edit(type) {
  $('title').textContent = type ? 'Edit project type' : 'New project type';
  $('fields').innerHTML = fields(type);
  const dialog = $('dialog'); dialog.showModal();
  dialog.onclose = async () => {
    if (dialog.returnValue !== 'default') return;
    const form = new FormData(dialog.querySelector('form'));
    try {
      if (form.get('remove')) await api('/api/project-types/' + type.id, {method:'DELETE'});
      else {
        const value={name:form.get('name'),category:form.get('category'),description:form.get('description'),seat_templates:form.getAll('seat_templates')};
        await api('/api/project-types' + (type ? '/' + type.id : ''), {method:type?'PATCH':'POST',body:JSON.stringify(value)});
      }
      await load();
    } catch (error) { alert(error.message); }
  };
}

async function load() {
  state = await api('/api/state');
  $('list').innerHTML = (state.project_types || []).map(type => `<article class="card type-card" data-id="${type.id}"><div class="type-glyph">◇</div><div class="type-copy"><div class="type-title"><h2>${esc(type.name)}</h2><span>${esc(type.category)}</span></div><p>${esc(type.description || 'No description')}</p></div><small>${type.seat_templates.length} seat${type.seat_templates.length===1?'':'s'}</small></article>`).join('') || '<div class="empty">No project types yet.</div>';
  document.querySelectorAll('[data-id]').forEach(node => node.onclick=()=>edit(state.project_types.find(item=>item.id===node.dataset.id)));
}
$('add').onclick=()=>edit();
document.addEventListener('click',event=>{if(event.target.matches('dialog button[value="cancel"]')){event.preventDefault();event.target.closest('dialog').close('cancel')}});
load().catch(error=>{$('list').innerHTML=`<div class="err">${esc(error.message)}</div>`});
