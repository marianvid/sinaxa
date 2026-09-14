document.documentElement.dataset.theme = localStorage.getItem('sinaxa-theme') || 'dark';

/* ------------------------------------------------------------------ state */
let S = null;              /* last /api/state payload */
let PROJECT = null, SESSION = null, ROOM = null;
let OPEN = true;           /* is the session expanded in the sidebar */
let SEL = new Set();       /* seat ids picked with cmd/ctrl-click */
let STICK = true;          /* was the thread at the bottom before this render */
let POLL = null, SENDING = false;
let PASTED = [];           /* images pasted, not yet sent */

const esc = s => String(s == null ? '' : s)
  .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const el = id => document.getElementById(id);
const hhmm = ts => { const d = new Date(ts*1000);
  return String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0'); };

const names = () => (S.members || []).map(m => m.name).join('|');
const fmt = s => esc(s)
  .replace(/```([\s\S]*?)```/g,(m,c)=>'<pre>'+c.replace(/^\n/,'')+'</pre>')
  .replace(/`([^`\n]+)`/g,'<code>$1</code>')
  .replace(new RegExp('@('+(names()||'\\w+')+')\\b','g'),'<span class="mention">@$1</span>');

const project  = () => (S.projects || []).find(p => p.id === PROJECT);
const session  = () => (project() || {sessions:[]}).sessions.find(s => s.id === SESSION);
const room     = () => (S.rooms || []).find(r => r.id === ROOM) || (S.rooms || [])[0];
const mainRm   = () => (S.rooms || []).find(r => r.kind === 'all');
const subs     = () => (S.rooms || []).filter(r => r.kind === 'custom');
const seatById = id => (S.seats || []).find(s => s.id === id);
const privateOf= seat => (S.rooms || []).find(
  r => r.kind === 'private' && r.seats.length === 1 && r.seats[0] === seat.id);
const memberById = id => (S.members || []).find(m => m.id === id);
const initial  = m => (m && m.name ? m.name[0].toUpperCase() : '·');
const liveOf   = seatId => ((S.status || {}).agents || [])
  .find(a => a.seat === seatId) || {};
const agents   = () => (S.members || []).filter(m => m.kind !== 'human');

/* ------------------------------------------------------------------ sidebar */
function renderTree(){
  const node = el('projnode'), box = el('tree');
  const p = project();
  node.innerHTML = p
    ? `<span class="t">${esc(p.name)}</span>
       <span class="toggle" id="addsess" title="New session">+</span>`
    : '<span class="t" style="color:var(--dim2)">no project yet</span>';
  if (p){
    node.querySelector('.t').onclick = projectMenu;
    node.oncontextmenu = e => { e.preventDefault(); projectMenu(); };
    el('addsess').onclick = e => { e.stopPropagation(); addSession(); };
  }

  box.innerHTML = '';
  if (!p) return;

  p.sessions.forEach(ses => {
    const open = ses.id === SESSION && OPEN;
    const row = document.createElement('div');
    row.className = 'sess' + (ses.id === SESSION && ROOM === (mainRm()||{}).id ? ' on' : '');
    row.innerHTML = `<span class="arrow ${open ? 'open' : ''}"
        title="${open ? 'collapse' : 'expand'}">▶</span>
      <span class="t">${esc(ses.name)}</span>
      <span class="toggle" title="Remove session">×</span>`;
    /* the arrow expands, the label selects — two different things */
    row.querySelector('.arrow').onclick = e => { e.stopPropagation();
      if (ses.id !== SESSION){ SESSION = ses.id; ROOM = null; OPEN = true; return refresh(); }
      OPEN = !OPEN; render(); };
    row.querySelector('.t').onclick = () => {
      SESSION = ses.id; ROOM = (ses.id === SESSION && mainRm()) ? mainRm().id : null;
      SEL.clear(); refresh(); };
    row.querySelector('.toggle').onclick = e => { e.stopPropagation();
      removeSession(ses); };
    box.appendChild(row);
    if (ses.id !== SESSION || !OPEN) return;

    const kids = document.createElement('div'); kids.className = 'sub';

    /* One entry per seat. A plain click selects it and opens its room;
       cmd/ctrl-click adds a second seat to the selection; right-clicking the
       selection offers to make a room out of it. */
    (S.seats || []).forEach(seat => {
      const mem = memberById(seat.occupant);
      const priv = privateOf(seat);
      const node = document.createElement('div');
      node.className = 'room' + (priv && priv.id === ROOM ? ' on' : '')
                     + (SEL.has(seat.id) ? ' sel' : '') + (seat.trouble ? ' free' : '');
      node.innerHTML = `<span class="t">${esc(seat.role)}</span>`
        + `<span class="sw" style="background:${mem ? mem.colour : 'var(--bg3)'}">${
             esc(mem ? initial(mem) : '!')}</span>`;
      node.onclick = e => {
        e.stopPropagation();
        if (e.metaKey || e.ctrlKey){
          SEL.has(seat.id) ? SEL.delete(seat.id) : SEL.add(seat.id);
          return render();
        }
        SEL = new Set([seat.id]);
        if (priv) ROOM = priv.id;
        refresh();
      };
      node.oncontextmenu = e => {
        if (!SEL.has(seat.id)) SEL = new Set([seat.id]);
        render(); seatMenu(e);
      };
      kids.appendChild(node);
    });

    /* Rooms you define yourself: the lead plus a chosen few. */
    subs().forEach(r => {
      const node = document.createElement('div');
      node.className = 'room' + (r.id === ROOM ? ' on' : '');
      node.innerHTML = `<span class="t"># ${esc(r.name)}</span>
        <span class="toggle" title="Remove room">×</span>`;
      node.onclick = e => { e.stopPropagation(); ROOM = r.id; SEL.clear(); refresh(); };
      node.querySelector('.toggle').onclick = e => { e.stopPropagation(); removeRoom(r); };
      kids.appendChild(node);
    });

    box.appendChild(kids);
  });
}

/* --------------------------------------------------------------- header
   Everything about who is in the team lives here: the breadcrumb, then one
   pill per seat. A seat is the way into its occupant's room. */
function renderHead(){
  const t = el('title'), p = project(), ses = session();
  t.innerHTML = `<span class="proj">${esc(p ? p.name : 'sinaxa')}</span>`
    + (ses ? `<span class="dot">/</span><span class="sess" data-go>${esc(ses.name)}</span>` : '');
  if (ses) t.querySelector('[data-go]').onclick = () => {
    ROOM = mainRm() ? mainRm().id : null; refresh(); };

  const bar = el('seatbar'); bar.innerHTML = '';
  (S.seats || []).forEach(seat => {
    const mem = memberById(seat.occupant);
    const a = liveOf(seat.id);
    const priv = privateOf(seat);
    const busy = (S.busy || []).includes(seat.id);
    const pill = document.createElement('span');
    pill.className = 'pers' + (seat.trouble ? ' free' : '') + (busy ? ' busy' : '')
                   + (priv && priv.id === ROOM ? ' on' : '');
    pill.title = seat.trouble ? seat.trouble
      : `${esc(seat.prompt_effective).slice(0,160)}`
        + `\n\n${a.provider || (mem ? mem.engine : '')} · ${a.model || (mem ? mem.model : '') || 'default'}`
        + `\n${a.turns || 0} turns · ${a.tokens || 0} tokens`;
    pill.innerHTML = `<span class="sw" style="background:${mem ? mem.colour : ''}">${
        esc(mem ? initial(mem) : '·')}</span>`
      + `<span>${esc(seat.name)}</span><span class="role">${esc(seat.role)}</span>`
      + (busy ? ' <span class="act">answering…</span>' : '');
    if (priv) pill.onclick = () => { ROOM = priv.id; SEL.clear(); refresh(); };
    bar.appendChild(pill);
  });
}

/* ------------------------------------------------------------------ thread */
function renderThread(){
  const r = room(), th = el('thread');
  th.className = 'thread';
  STICK = th.scrollTop + th.clientHeight >= th.scrollHeight - 40;
  if (!r){
    th.innerHTML = '<div class="empty">No project yet.<br>'
      + 'Add one from the + beside Projects — but define your members and '
      + 'seats first.</div>';
    return;
  }
  const messages = S.messages || [];
  if (!messages.length){
    th.innerHTML = '<div class="empty">Empty room.<br>'
      + 'Write something — @Name for one of them, nothing for everyone.</div>';
    return;
  }
  th.innerHTML = messages.map(m => {
    if (m.kind === 'error') return `<div class="err">${esc(m.author_name)}: ${esc(m.text)}</div>`;
    if (m.kind === 'system') return `<div class="sys"><span>${esc(m.text)}</span></div>`;
    const lead = m.author === 'lead';
    const seat = lead ? null : seatById(m.author);
    const mem  = lead ? (S.lead || {}) : (seat ? memberById(seat.occupant) : null);
    const colour = lead ? ((S.lead || {}).colour || 'var(--lead)')
                        : (mem ? mem.colour : 'var(--bg3)');
    const meta = m.meta || {};
    const tags = (mem && mem.model ? `<span class="tag">${esc(mem.model)}</span>` : '')
      + (meta.elapsed !== undefined ? `<span class="tag">${meta.elapsed}s</span>` : '')
      + (meta.tokens ? `<span class="tag">${meta.tokens} tok</span>` : '')
      + (meta.blind ? `<span class="blind">did not see ${meta.blind} image${
            meta.blind === 1 ? '' : 's'}</span>` : '')
      + (lead ? '<span class="lb">★ lead</span>' : '');
    return `<div class="msg"><div class="av" style="background:${colour}">${
        esc(initial({name: m.author_name}))}</div><div>
      <div class="who"><b>${esc(m.author_name)}</b>${tags}<span class="time">${hhmm(m.ts)}</span></div>
      <div class="bd">${fmt(m.text)}</div>${shots(m)}</div></div>`;
  }).join('');
  /* The scroll is applied at the end of render(), not here: the status bar
     is filled after this and takes height away from the thread, so scrolling
     now would land short by exactly that much. */
}

/* An image lives beside the transcript; the page asks the server for it by
   name rather than carrying it around in the state payload. */
function shots(m){
  if (!(m.images || []).length) return '';
  return '<div class="shots">' + m.images.map(n =>
    `<a href="/api/files/${n}?project=${PROJECT}&session=${SESSION}" target="_blank">
       <img src="/api/files/${n}?project=${PROJECT}&session=${SESSION}" alt=""></a>`
  ).join('') + '</div>';
}

function renderPasted(){
  const box = el('pasted');
  box.innerHTML = PASTED.map((p, i) =>
    `<span class="shot"><img src="${p.url}" alt=""><u data-drop="${i}"
       title="remove">×</u></span>`).join('');
  box.style.display = PASTED.length ? '' : 'none';
  box.querySelectorAll('[data-drop]').forEach(x =>
    x.onclick = () => { PASTED.splice(+x.dataset.drop, 1); renderPasted(); });
}

/* ------------------------------------------------------------------ status */
function renderStatus(){
  const s = S.status || {}, bar = el('statusbar');
  if (!s.agents){
    bar.innerHTML = `<b>${(S.projects || []).length}</b> projects<span class="sep">·</span>`
      + `<b>${(S.members || []).length}</b> members<span class="sep">·</span>`
      + `<b>${(S.seat_defs || []).length}</b> roles`;
    return;
  }
  const engines = (s.engines || []).filter(e => e.alive).map(e => e.label).join(', ');
  bar.innerHTML =
     `<b>${esc(engines || 'nothing started')}</b><span class="sep">|</span>`
    +`<b>${s.seats}</b> seats<span class="sep">·</span>`
    +`<b>${s.agents.length}</b> conversations<span class="sep">·</span>`
    +`<b>${(s.processes || []).length}</b> processes<span class="sep">·</span>`
    +(s.total_rss_mb ? `<b>${s.total_rss_mb}</b> MB<span class="sep">·</span>` : '')
    +`<b>${s.turns}</b> turns<span class="sep">·</span>`
    +`<b>${(s.tokens || 0).toLocaleString()}</b> tokens`;
}

function render(){
  renderTree(); renderHead();
  renderThread();
  renderStatus();

  const r = room();
  el('composer').style.display = r ? '' : 'none';
  el('managebtn').style.display = SESSION ? '' : 'none';
  el('sendbtn').disabled = SENDING;
  if (r) el('input').placeholder = r.kind === 'private'
      ? 'Message ' + ((seatById(r.seats[0]) || {}).name || r.name) + '…'
      : 'Message the room…   @Name to address one';
  if (STICK) requestAnimationFrame(() => {
    const th = el('thread'); th.scrollTop = th.scrollHeight; });
}

/* --------------------------------------------------------------- selection
   A room is the lead plus the agents you picked, so it takes at least two
   seats to be worth making — one is the private room you already have. */
function closeMenu(){ document.querySelectorAll('.ctx').forEach(m => m.remove()); }
document.addEventListener('click', closeMenu);

function menuAt(ev, html){
  closeMenu();
  const menu = document.createElement('div'); menu.className = 'ctx';
  menu.innerHTML = html;
  document.body.appendChild(menu);
  menu.style.left = Math.min(ev.clientX, innerWidth  - menu.offsetWidth  - 8) + 'px';
  menu.style.top  = Math.min(ev.clientY, innerHeight - menu.offsetHeight - 8) + 'px';
  return menu;
}

function seatMenu(ev){
  ev.preventDefault(); ev.stopPropagation();
  const picked = [...SEL].map(id => seatById(id)).filter(Boolean);
  const who = picked.map(x => x.name);
  const enough = picked.length >= 2;
  const menu = menuAt(ev, `<div class="hdr">${esc(who.join(' · ')) || 'nothing selected'}</div>
    <button data-make><i>▤</i>Create a room</button>
    ${enough ? '' : '<div class="hint2">cmd-click a second seat</div>'}`);
  const make = menu.querySelector('[data-make]');
  if (!enough){ make.disabled = true; make.title = 'pick a second seat with cmd-click'; }
  else make.onclick = e => { e.stopPropagation(); closeMenu(); newRoom(picked); };
}

function projectMenu(ev){
  const event = ev || {clientX: 20, clientY: 60};
  const menu = menuAt(event, `<div class="hdr">${esc((project()||{}).name || '')}</div>`
    + (S.projects || []).map(p =>
        `<button data-go="${p.id}"><i>${p.id === PROJECT ? '✓' : ''}</i>${esc(p.name)}</button>`).join('')
    + `<div class="rule"></div>
       <button data-new><i>+</i>New project</button>
       <button data-drop><i>×</i>Remove this project</button>`);
  menu.querySelectorAll('[data-go]').forEach(b =>
    b.onclick = e => { e.stopPropagation(); closeMenu();
      PROJECT = b.dataset.go; SESSION = null; ROOM = null; SEL.clear(); refresh(); });
  menu.querySelector('[data-new]').onclick = e => { e.stopPropagation(); closeMenu(); addProject(); };
  menu.querySelector('[data-drop]').onclick = e => { e.stopPropagation(); closeMenu(); removeProject(); };
}

/* ------------------------------------------------------------------ dialogs */
function closeModal(){ document.querySelectorAll('.scrim').forEach(s => s.remove()); }

function modal(html, onOk, okLabel, danger){
  closeModal();
  const scrim = document.createElement('div'); scrim.className = 'scrim';
  scrim.innerHTML = `<div class="modal${danger === 'wide' ? ' wide' : ''}">${html}
    <div class="foot"><button class="btn" data-x>Cancel</button>
      ${onOk ? `<button class="btn ${danger === true ? 'danger' : 'primary'}" data-ok>${
        esc(okLabel || 'Confirm')}</button>` : ''}</div></div>`;
  document.body.appendChild(scrim);
  scrim.onclick = e => { if (e.target === scrim) closeModal(); };
  scrim.querySelector('[data-x]').onclick = closeModal;
  const ok = scrim.querySelector('[data-ok]');
  if (ok) ok.onclick = () => act(onOk).then(closeModal);
  return scrim;
}

/* Save stays dead until something changed -- a button that saves what is
   already saved teaches you to press it without reading.

   Creating is the exception: a new room arrives with its name already filled
   in, and there is nothing to change before it is worth making. So `fresh`
   asks only that the form be valid. */
function watch(root, button, valid, fresh){
  if (!button) return null;
  const fields = () => Array.from(root.querySelectorAll('input,select,textarea'));
  const snap = () => fields().map(f => f.type === 'checkbox' ? String(f.checked) : f.value).join('|');
  let saved = snap();
  const check = () => {
    const ok = !valid || valid(root);
    button.disabled = !(ok && (fresh || snap() !== saved));
  };
  root.addEventListener('input', check);
  root.addEventListener('change', check);
  check();
  return {check, rebase: () => { saved = snap(); check(); }};
}
const filled = (root, sel) =>
  Array.from(root.querySelectorAll(sel)).every(f => f.value.trim());

/* ----------------------------------------------------------- manage team */
function manageTeam(){
  const taken = new Set((S.seats || []).map(s => s.seat_def));
  const free = (S.seat_defs || []).filter(d => !taken.has(d.id));

  const rows = (S.seats || []).map(seat => `
    <div class="seatrow" data-seat="${seat.id}" style="align-items:flex-start">
      <div style="flex:0 0 118px">
        <b style="font-size:12.5px">${esc(seat.role)}</b>
        <select class="whosel" style="margin-top:6px">
          ${agents().map(m => `<option value="${m.id}" ${
              m.id === seat.occupant ? 'selected' : ''}>${esc(m.name)}</option>`).join('')}
        </select>
      </div>
      <div style="flex:1;min-width:0">
        <textarea class="promptin" rows="3">${esc(seat.prompt_effective)}</textarea>
        <div class="why" style="color:var(--dim2);font-size:11px">${seat.overridden
          ? 'this session’s own wording'
          : 'the role’s wording, as defined in Seats'}</div>
      </div>
      <div style="display:flex;flex-direction:column;gap:4px;flex:none">
        <button class="btn" data-save>Save</button>
        <button class="btn" data-reset ${seat.overridden ? '' : 'disabled'}>Reset to default</button>
        <button class="btn" data-clear>Clear context</button>
        <button class="btn danger" data-drop>Remove seat</button>
      </div>
    </div>`).join('');

  const scrim = modal(`<h3>Manage team</h3>
    <div class="lead">Seats belong to the session. A seat is a role; who fills
      it can change without the seat losing its place in the rooms.</div>
    <div class="seatlist">${rows || '<div class="empty">No seats yet.</div>'}</div>
    <div class="seatrow" style="margin-top:8px">
      <select class="rolesel" id="newDef" style="flex:0 0 122px">
        ${free.map(d => `<option value="${d.id}">${esc(d.role)}</option>`).join('')
          || '<option value="">every role is seated</option>'}
      </select>
      <select class="whosel" id="newWho">
        ${agents().map(m => `<option value="${m.id}">${esc(m.name)}</option>`).join('')}
      </select>
      <button class="btn" id="addSeat" ${free.length ? '' : 'disabled'}>Add seat</button>
    </div>`, null, null, 'wide');

  const by = {}; (S.seats || []).forEach(s => { by[s.id] = s; });
  const where = `?project=${PROJECT}&session=${SESSION}`;

  scrim.querySelectorAll('[data-seat]').forEach(row => {
    const seat = by[row.dataset.seat];
    const box = row.querySelector('.promptin');
    const save = row.querySelector('[data-save]');
    const reset = row.querySelector('[data-reset]');
    watch(row, save, r => filled(r, 'textarea'));

    save.onclick = () => act(async () => {
      /* The box always shows the prompt in force. Leaving it as the role
         wrote it means no override at all — the server reads a blank as
         "use the role's". */
      const written = box.value;
      const same = written.trim() === (seat.prompt_default || '').trim();
      const answer = await api('PATCH', '/api/seats/' + seat.id, {
        project: PROJECT, session: SESSION,
        occupant: row.querySelector('.whosel').value,
        prompt: same ? '' : written});
      if (answer.warning) toast(answer.warning);
    }).then(closeModal);

    reset.onclick = () => {
      box.value = seat.prompt_default || '';
      row.querySelector('.why').textContent =
        'the role’s wording — edit it to make it this session’s own';
      reset.disabled = true;
      box.dispatchEvent(new Event('input', {bubbles: true}));
      box.focus();
    };
    row.querySelector('[data-clear]').onclick = () => act(() =>
      api('POST', '/api/seats/' + seat.id + '/clear',
          {project: PROJECT, session: SESSION}));
    row.querySelector('[data-drop]').onclick = () => act(() =>
      api('DELETE', '/api/seats/' + seat.id + where)).then(closeModal);
  });

  if (el('addSeat')) el('addSeat').onclick = () => act(() =>
    api('POST', '/api/seats', {project: PROJECT, session: SESSION,
      seat_def: el('newDef').value, occupant: el('newWho').value})).then(closeModal);
}

/* --------------------------------------------------------------- projects */
function addProject(){
  const scrim = modal(`<h3>New project</h3>
    <div class="lead">It starts with a session called main, a seat for every
      role that has a default member, and a room each.</div>
    <label class="field">Name <input id="pName"></label>
    <label class="field">Folder <input id="pCwd" placeholder="where the agents will read"></label>`,
  async () => {
    await api('POST', '/api/projects', {name: el('pName').value.trim(),
                                        cwd: el('pCwd').value.trim() || null});
    PROJECT = null; SESSION = null; ROOM = null;
  }, 'Create');
  watch(scrim, scrim.querySelector('[data-ok]'), r => filled(r, '#pName'), true);
}

function removeProject(){
  const p = project(); if (!p) return;
  modal(`<h3>Remove ${esc(p.name)}</h3>
    <div class="lead">The project leaves the list. Its transcripts stay on
      disk unless you say otherwise.</div>
    <label class="checkline"><input type="checkbox" id="pErase">
      also erase them from the disk</label>`,
  async () => {
    await api('DELETE', '/api/projects/' + p.id + (el('pErase').checked ? '?erase=1' : ''));
    PROJECT = null; SESSION = null; ROOM = null;
  }, 'Remove', true);
}

function addSession(){
  const scrim = modal(`<h3>New session</h3>
    <div class="lead">A session starts empty — add its seats from Manage team.</div>
    <label class="field">Name <input id="sName"></label>`,
  async () => {
    const answer = await api('POST', '/api/sessions',
      {project: PROJECT, name: el('sName').value.trim()});
    SESSION = answer.session.id; ROOM = null; OPEN = true;
  }, 'Create');
  watch(scrim, scrim.querySelector('[data-ok]'), r => filled(r, '#sName'), true);
}

function removeSession(ses){
  modal(`<h3>Remove ${esc(ses.name)}</h3>
    <div class="lead">Its seats and rooms go with it.</div>
    <label class="checkline"><input type="checkbox" id="sErase">
      also erase its transcripts from the disk</label>`,
  async () => {
    await api('DELETE', '/api/sessions/' + ses.id
      + (el('sErase').checked ? '?erase=1&' : '?') + 'project=' + PROJECT);
    SESSION = null; ROOM = null;
  }, 'Remove', true);
}

function newRoom(picked){
  const scrim = modal(`<h3>New room</h3>
    <div class="lead">${esc(picked.map(s => s.name).join(', '))} — and you.</div>
    <label class="field">Name <input id="rName"
      value="${esc(picked.map(s => s.role).join('+'))}"></label>`,
  async () => {
    await api('POST', '/api/rooms', {project: PROJECT, session: SESSION,
      name: el('rName').value.trim(), seats: picked.map(s => s.id)});
    SEL.clear();
  }, 'Create');
  watch(scrim, scrim.querySelector('[data-ok]'), r => filled(r, '#rName'), true);
}

function removeRoom(r){
  modal(`<h3>Remove # ${esc(r.name)}</h3>
    <div class="lead">The seats stay; only this grouping goes.</div>
    <label class="checkline"><input type="checkbox" id="rErase">
      also erase its transcript from the disk</label>`,
  async () => {
    await api('DELETE', '/api/rooms/' + r.id
      + (el('rErase').checked ? '?erase=1&' : '?')
      + 'project=' + PROJECT + '&session=' + SESSION);
    ROOM = null;
  }, 'Remove', true);
}

/* ------------------------------------------------------------------ io */
async function api(method, path, body){
  const options = {method, headers: {'Content-Type': 'application/json'}};
  if (body !== undefined) options.body = JSON.stringify(body);
  const answer = await fetch(path, options);
  const data = await answer.json().catch(() => ({}));
  if (!answer.ok) throw new Error(data.error || answer.statusText);
  return data;
}

async function act(work){
  try { if (work) await work(); await refresh(); }
  catch (exc) { toast(exc.message); }
}

async function refresh(){
  const query = new URLSearchParams();
  if (PROJECT) query.set('project', PROJECT);
  if (SESSION) query.set('session', SESSION);
  if (ROOM) query.set('room', ROOM);
  S = await api('GET', '/api/state?' + query.toString());
  PROJECT = S.project || null;
  SESSION = S.session || null;
  ROOM = S.room || null;
  render();
  clearTimeout(POLL);
  POLL = setTimeout(refresh, (S.busy || []).length ? 700 : 2500);
}

async function send(){
  const box = el('input'), text = box.value.trim();
  if ((!text && !PASTED.length) || SENDING) return;
  box.value = ''; box.style.height = '38px';
  SENDING = true; el('sendbtn').disabled = true;
  const images = PASTED.map(p => ({type: p.type, data: p.data}));
  PASTED = []; renderPasted();
  try { await api('POST', '/api/say',
                  {project: PROJECT, session: SESSION, room: ROOM, text, images}); }
  catch (exc) { toast(exc.message); box.value = text; }
  SENDING = false;
  refresh();
}

let TT; function toast(t){ clearTimeout(TT);
  document.querySelectorAll('.toast').forEach(x => x.remove());
  const d = document.createElement('div'); d.className = 'toast'; d.textContent = t;
  document.body.appendChild(d); TT = setTimeout(() => d.remove(), 5000); }

el('addproj').onclick = addProject;
el('managebtn').onclick = manageTeam;
el('sendbtn').onclick = send;
/* Paste an image and it waits above the box until you send it. Files
   dragged in are the same thing by another route. */
async function takeImages(files){
  for (const file of files){
    if (!file || !/^image\//.test(file.type)) continue;
    const data = await new Promise(done => {
      const reader = new FileReader();
      reader.onload = () => done(String(reader.result).split(',')[1]);
      reader.readAsDataURL(file);
    });
    PASTED.push({type: file.type, data,
                 url: 'data:' + file.type + ';base64,' + data});
  }
  renderPasted();
}

el('input').addEventListener('paste', e => {
  const files = [...(e.clipboardData ? e.clipboardData.files : [])];
  if (!files.length) return;                 /* plain text: let it through */
  e.preventDefault();
  takeImages(files);
});
el('input').addEventListener('dragover', e => e.preventDefault());
el('input').addEventListener('drop', e => {
  if (!e.dataTransfer || !e.dataTransfer.files.length) return;
  e.preventDefault(); takeImages([...e.dataTransfer.files]);
});

el('input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); send(); }});
el('input').addEventListener('input', e => {
  e.target.style.height = '38px';
  e.target.style.height = Math.min(180, e.target.scrollHeight) + 'px'; });
refresh().then(() => el('input').focus());
