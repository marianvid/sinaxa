/* Members is deliberately self-contained: changing this page cannot change
   projects, seats, or settings. */
document.documentElement.dataset.theme = localStorage.getItem('sinaxa-theme') || 'dark';

let S = null;
const el = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const initial = m => (m && m.name ? m.name[0].toUpperCase() : '·');
const engineOf = id => (S.engines || []).find(e => e.id === id) || {};

function render(){
  const rows = (S.members || []).map(m => {
    const engine = engineOf(m.engine);
    return `<div class="row">
      <span class="sw" style="background:${m.colour}">${esc(initial(m))}</span>
      <span class="nm">${esc(m.name)}</span>
      <span class="meta">${m.kind === 'human' ? 'human · the lead' : esc(engine.label || m.engine)}</span>
      <span class="say">${esc(m.model || 'default model')}${m.effort ? ' · ' + esc(m.effort) : ''}${m.binary ? ' · ' + esc(m.binary) : ''}</span>
      <span class="tools">${m.kind === 'human' ? '' : `<button class="btn" data-edit="${m.id}">Edit</button><button class="btn danger" data-del="${m.id}">Remove</button>`}</span>
    </div>`;
  }).join('');
  el('content').innerHTML = `<h3>Members</h3>
    <div class="lead">Who can take a seat: you, and one entry per CLI engine.
      A member says how an occupant is started; its role belongs to the seat.</div>
    <div class="bar"><button class="btn primary" id="addmem">Add member</button></div>
    <div class="rows">${rows || '<div class="empty">Nobody yet.</div>'}</div>`;
  el('addmem').onclick = () => memberForm(null);
  document.querySelectorAll('[data-edit]').forEach(b =>
    b.onclick = () => memberForm((S.members || []).find(m => m.id === b.dataset.edit)));
  document.querySelectorAll('[data-del]').forEach(b =>
    b.onclick = () => act(() => api('DELETE', '/api/members/' + b.dataset.del)));
  renderStatus();
}

function renderStatus(){
  el('statusbar').innerHTML = `<b>${(S.projects || []).length}</b> projects<span class="sep">·</span>`
    + `<b>${(S.members || []).length}</b> members<span class="sep">·</span>`
    + `<b>${(S.seat_defs || []).length}</b> roles`;
}

function closeModal(){ document.querySelectorAll('.scrim').forEach(s => s.remove()); }
function modal(html, onOk, okLabel){
  closeModal();
  const scrim = document.createElement('div');
  scrim.className = 'scrim';
  scrim.innerHTML = `<div class="modal">${html}<div class="foot">
    <button class="btn" data-x>Cancel</button><button class="btn primary" data-ok>${esc(okLabel)}</button>
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
  let saved = snap();
  const check = () => { button.disabled = !((!valid || valid(root)) && (fresh || snap() !== saved)); };
  root.addEventListener('input', check);
  root.addEventListener('change', check);
  check();
  return {check, rebase: () => { saved = snap(); check(); }};
}
const filled = (root, selector) =>
  Array.from(root.querySelectorAll(selector)).every(field => field.value.trim());

function memberForm(member){
  const engines = S.engines || [];
  const chosen = member ? member.engine : (engines[0] || {}).id;
  const scrim = modal(`<h3>${member ? 'Edit member' : 'Add member'}</h3>
    <div class="lead">Configure the local CLI process used by this member.</div>
    <label class="field">Name <input id="mName" value="${esc(member ? member.name : '')}"></label>
    <label class="field">Engine <select id="mEngine">${engines.map(e =>
      `<option value="${e.id}" ${e.id === chosen ? 'selected' : ''}>${esc(e.label)}</option>`).join('')}</select>
      <div class="why" id="mWhy"></div></label>
    <label class="field">Model <span id="mModel"></span></label>
    <label class="field">Effort <span id="mEffort"></span></label>
    <label class="field">Binary <input id="mBinary" placeholder="leave empty for the default" value="${esc(member ? member.binary || '' : '')}"></label>`,
  async () => {
    const body = {name: el('mName').value.trim(), engine: el('mEngine').value,
      model: el('mModelIn') ? el('mModelIn').value.trim() : null,
      effort: el('mEffortIn') ? el('mEffortIn').value || null : null,
      binary: el('mBinary').value.trim() || null};
    if (member) await api('PATCH', '/api/members/' + member.id, body);
    else await api('POST', '/api/members', body);
  }, member ? 'Save' : 'Add');

  const guard = watch(scrim, scrim.querySelector('[data-ok]'),
    root => filled(root, '#mName'), !member);
  const paint = async () => {
    const engine = engineOf(el('mEngine').value);
    el('mWhy').textContent = engine.note || '';
    const current = member && member.engine === engine.id ? member.model || '' : '';
    let models = engine.models || [];
    if (engine.models_from_engine) {
      el('mModel').innerHTML = '<i class="why">asking the engine…</i>';
      models = (await api('GET', '/api/models?engine=' + engine.id).catch(() => ({models: []}))).models;
    }
    el('mModel').innerHTML = models.length && !engine.models_are_a_hint
      ? `<select id="mModelIn">${models.map(m => `<option ${m === current ? 'selected' : ''}>${esc(m)}</option>`).join('')}</select>`
      : `<input id="mModelIn" list="mList" value="${esc(current)}"><datalist id="mList">${models.map(m => `<option>${esc(m)}</option>`).join('')}</datalist>`;
    const efforts = engine.efforts || [];
    el('mEffort').innerHTML = efforts.length
      ? `<select id="mEffortIn">${efforts.map(e => `<option ${((member && member.effort) || engine.effort_default) === e ? 'selected' : ''}>${esc(e)}</option>`).join('')}</select>`
      : '<i class="why">not set here for this engine</i>';
  };
  el('mEngine').onchange = () => paint().then(guard.check);
  paint().then(guard.rebase);
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
