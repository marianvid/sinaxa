/* Settings reports engine capabilities; global appearance lives in the top bar. */
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
  const summary = `<div class="setting-line"><span><b>Workspace catalog</b><small>Reusable configuration available to every project</small></span><b>${(S.members||[]).filter(item=>item.kind==='agent').length} agents · ${(S.seat_templates||[]).length} seats · ${(S.project_types||[]).length} types</b></div>
    <div class="setting-line"><span><b>Project isolation</b><small>Each open project owns independent lazy engine runtimes</small></span><b>Enabled</b></div>
    <div class="setting-line"><span><b>Appearance</b><small>Theme is stored only in this browser</small></span><b>${esc(document.documentElement.dataset.theme || 'dark')}</b></div>`;
  el('content').innerHTML = `<h3>Settings</h3>
    <div class="lead">Workspace-wide behavior and a compact system overview.
      Provider details remain in Engines; model identity remains in Agents.</div>
    <div class="settings-group"><h4>Workspace</h4>${summary}</div>
    <div class="settings-group"><h4>Available engines</h4>${engines || '<div class="empty">No engines reported.</div>'}</div>`;
}

async function refresh(){
  const response = await fetch('/api/state');
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || response.statusText);
  S = data; render();
}
refresh().catch(error => { el('content').innerHTML = `<div class="err">${esc(error.message)}</div>`; });
