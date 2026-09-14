/* Settings owns browser-local preferences and reports engine capabilities. */
const savedTheme = localStorage.getItem('sinaxa-theme') || 'dark';
document.documentElement.dataset.theme = savedTheme;

let S = null;
const el = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

function render(){
  const engines = (S.engines || []).map(engine => `<div class="setting-card">
    <div class="setting-head"><b>${esc(engine.name)}</b><span class="tag">${esc(engine.id)}</span></div>
    <div class="setting-copy">${engine.enabled ? 'Enabled' : 'Disabled'} · ${esc(engine.mode)} · ${engine.max_concurrency} concurrent turns</div>
    <div class="setting-meta">Executable: ${esc(engine.executable || engine.kind)}</div>
    <div class="setting-meta">MCP: ${esc((engine.mcp_servers || []).join(', ') || 'none configured')}</div>
  </div>`).join('');
  el('content').innerHTML = `<h3>Settings</h3>
    <div class="lead">Preferences on this page are local to this browser. CLI
      member configuration remains isolated on the Members page.</div>
    <div class="settings-group"><h4>Appearance</h4>
      <label class="setting-line"><span><b>Theme</b><small>Used by all four Sinaxa pages.</small></span>
        <select id="theme"><option value="dark">Dark</option><option value="light">Light</option></select>
      </label>
    </div>
    <div class="settings-group"><h4>Available engines</h4>${engines || '<div class="empty">No engines reported.</div>'}</div>`;
  el('theme').value = document.documentElement.dataset.theme;
  el('theme').onchange = event => {
    const theme = event.target.value;
    localStorage.setItem('sinaxa-theme', theme);
    document.documentElement.dataset.theme = theme;
  };
  el('statusbar').innerHTML = `<b>${(S.engines || []).length}</b> engines<span class="sep">·</span>`
    + `<b>${(S.members || []).length}</b> members<span class="sep">·</span>`
    + `<b>${(S.engines || []).length}</b> engines`;
}

async function refresh(){
  const response = await fetch('/api/state');
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || response.statusText);
  S = data; render();
}
refresh().catch(error => { el('content').innerHTML = `<div class="err">${esc(error.message)}</div>`; });
