const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>]/g, character => (
  {'&': '&amp;', '<': '&lt;', '>': '&gt;'}[character]
));

async function load() {
  const response = await fetch('/api/state');
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || response.statusText);
  const project = (data.projects || []).find(item => item.id === data.project);
  $('list').innerHTML = (data.seats || []).map(seat => `<article class="card seat-card ${seat.trouble ? 'trouble' : ''}">
    <h2>${esc(seat.role)}</h2>
    <p>${esc(seat.name || 'Unoccupied')}</p>
    <small>${esc(project?.name || '')}</small>
  </article>`).join('') || '<div class="empty">No seats in the current project.</div>';
}

load().catch(error => { $('list').innerHTML = `<div class="err">${esc(error.message)}</div>`; });
