/* Seats is deliberately self-contained: this file owns only role definitions. */
document.documentElement.dataset.theme = localStorage.getItem('sinaxa-theme') || 'dark';

let S = null;
const el = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const initial = m => (m && m.name ? m.name[0].toUpperCase() : '·');
const memberById = id => (S.members || []).find(m => m.id === id);
const agents = () => (S.members || []).filter(m => m.kind !== 'human');

function render(){
  const rows = (S.seat_defs || []).map(definition => {
    const member = memberById(definition.default_member);
    return `<div class="row">
      <span class="sw" style="background:${member ? member.colour : 'var(--bg3)'}">${esc(member ? initial(member) : '·')}</span>
      <span class="nm">${esc(definition.role)}</span>
      <span class="meta">${esc(member ? member.name : 'no default member')}</span>
      <span class="say">${esc(definition.prompt)}</span>
      <span class="tools"><button class="btn" data-edit="${definition.id}">Edit</button><button class="btn danger" data-del="${definition.id}">Remove</button></span>
    </div>`;
  }).join('');
  el('content').innerHTML = `<h3>Seats</h3>
    <div class="lead">Reusable roles for the whole workspace. Each role has
      its own instructions and may name a default member.</div>
    <div class="bar"><button class="btn primary" id="adddef">Add role</button></div>
    <div class="rows">${rows || '<div class="empty">No roles yet.</div>'}</div>`;
  el('adddef').onclick = () => seatForm(null);
  document.querySelectorAll('[data-edit]').forEach(b =>
    b.onclick = () => seatForm((S.seat_defs || []).find(d => d.id === b.dataset.edit)));
  document.querySelectorAll('[data-del]').forEach(b =>
    b.onclick = () => act(() => api('DELETE', '/api/seatdefs/' + b.dataset.del)));
  renderStatus();
}

function renderStatus(){
  el('statusbar').innerHTML = `<b>${(S.projects || []).length}</b> projects<span class="sep">·</span>`
    + `<b>${(S.members || []).length}</b> members<span class="sep">·</span>`
    + `<b>${(S.seat_defs || []).length}</b> roles`;
}

function closeModal(){ document.querySelectorAll('.scrim').forEach(s => s.remove()); }
function modal(html, onOk, label){
  closeModal();
  const scrim = document.createElement('div'); scrim.className = 'scrim';
  scrim.innerHTML = `<div class="modal">${html}<div class="foot">
    <button class="btn" data-x>Cancel</button><button class="btn primary" data-ok>${esc(label)}</button>
  </div></div>`;
  document.body.appendChild(scrim);
  scrim.onclick = e => { if (e.target === scrim) closeModal(); };
  scrim.querySelector('[data-x]').onclick = closeModal;
  scrim.querySelector('[data-ok]').onclick = async () => {
    if (await act(onOk)) closeModal();
  };
  return scrim;
}
function watch(root, button, valid, fresh){
  const fields = () => Array.from(root.querySelectorAll('input,select,textarea'));
  const snap = () => fields().map(f => f.value).join('|');
  const saved = snap();
  const check = () => { button.disabled = !((!valid || valid(root)) && (fresh || snap() !== saved)); };
  root.addEventListener('input', check); root.addEventListener('change', check); check();
}
const filled = (root, selector) =>
  Array.from(root.querySelectorAll(selector)).every(field => field.value.trim());

function seatForm(definition){
  const scrim = modal(`<h3>${definition ? 'Edit role' : 'Add role'}</h3>
    <div class="lead">The prompt is required: a role without instructions is not a usable seat.</div>
    <label class="field">Role <input id="dRole" value="${esc(definition ? definition.role : '')}"></label>
    <label class="field">Prompt <textarea id="dPrompt" rows="6">${esc(definition ? definition.prompt : '')}</textarea></label>
    <label class="field">Default member <select id="dWho"><option value="">— none —</option>
      ${agents().map(m => `<option value="${m.id}" ${definition && definition.default_member === m.id ? 'selected' : ''}>${esc(m.name)}</option>`).join('')}
    </select><div class="why">New projects create a seat for every role that has a default member.</div></label>`,
  async () => {
    const body = {role: el('dRole').value.trim(), prompt: el('dPrompt').value,
      default_member: el('dWho').value || null};
    if (definition) await api('PATCH', '/api/seatdefs/' + definition.id, body);
    else await api('POST', '/api/seatdefs', body);
  }, definition ? 'Save' : 'Add');
  watch(scrim, scrim.querySelector('[data-ok]'),
    root => filled(root, '#dRole, #dPrompt'), !definition);
}

async function api(method, path, body){
  const options = {method, headers: {'Content-Type': 'application/json'}};
  if (body !== undefined) options.body = JSON.stringify(body);
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}
async function act(work){
  try { await work(); await refresh(); return true; }
  catch (error) { toast(error.message); return false; }
}
async function refresh(){ S = await api('GET', '/api/state'); render(); }
let toastTimer;
function toast(text){
  clearTimeout(toastTimer);
  document.querySelectorAll('.toast').forEach(x => x.remove());
  const node = document.createElement('div'); node.className = 'toast'; node.textContent = text;
  document.body.appendChild(node); toastTimer = setTimeout(() => node.remove(), 5000);
}
refresh().catch(error => toast(error.message));
