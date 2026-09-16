const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, character => (
  {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]
));
let state = {};

async function api(path, options={}) {
  const response = await fetch(path, {headers:{'Content-Type':'application/json'}, ...options});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

const agents = () => (state.members || []).filter(member => member.kind === 'agent');
const agentName = id => agents().find(agent => agent.id === id)?.name || 'No default agent';

function fields(template={}) {
  return `<label>Role<input name="role" value="${esc(template.role)}" required></label>
    <label>Category<select name="category">
      ${['general','software','editorial','creative','media'].map(category =>
        `<option value="${category}" ${template.category===category?'selected':''}>${category}</option>`).join('')}
    </select></label>
    <label>Default agent<select name="default_agent"><option value="">Unassigned</option>
      ${agents().map(agent => `<option value="${agent.id}" ${template.default_agent===agent.id?'selected':''}>${esc(agent.name)}</option>`).join('')}
    </select></label>
    <label>Default instructions<textarea name="prompt" rows="5" required>${esc(template.prompt)}</textarea></label>
    ${template.id ? '<label class="danger"><input type="checkbox" name="remove"> Remove template</label>' : ''}`;
}

function edit(template) {
  $('title').textContent = template ? 'Edit seat template' : 'New seat template';
  $('fields').innerHTML = fields(template);
  const dialog = $('dialog');
  dialog.showModal();
  dialog.onclose = async () => {
    if (dialog.returnValue !== 'default') return;
    const form = new FormData(dialog.querySelector('form'));
    try {
      if (form.get('remove')) {
        await api('/api/seat-templates/' + template.id, {method:'DELETE'});
      } else {
        const value = {role:form.get('role'), category:form.get('category'),
          default_agent:form.get('default_agent') || null, prompt:form.get('prompt')};
        await api('/api/seat-templates' + (template ? '/' + template.id : ''),
          {method:template ? 'PATCH' : 'POST', body:JSON.stringify(value)});
      }
      await load();
    } catch (error) { alert(error.message); }
  };
}

async function load() {
  state = await api('/api/state');
  $('list').innerHTML = (state.seat_templates || []).map(template => `<article class="card seat-card" data-id="${template.id}">
    <div class="seat-glyph">▦</div>
    <div class="seat-copy"><div class="seat-title"><h2>${esc(template.role)}</h2><span>${esc(template.category)}</span></div>
    <p>${esc(template.prompt)}</p></div>
    <small>${esc(agentName(template.default_agent))}</small>
  </article>`).join('') || '<div class="empty">No seat templates yet.</div>';
  document.querySelectorAll('[data-id]').forEach(node => {
    node.onclick = () => edit(state.seat_templates.find(item => item.id === node.dataset.id));
  });
}

$('add').onclick = () => edit();
document.addEventListener('click', event => {
  if (event.target.matches('dialog button[value="cancel"]')) {
    event.preventDefault(); event.target.closest('dialog').close('cancel');
  }
});
load().catch(error => { $('list').innerHTML = `<div class="err">${esc(error.message)}</div>`; });
