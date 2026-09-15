(() => {
  const root = document.documentElement;
  const toggle = document.getElementById('themeToggle');

  function applyTheme(theme) {
    root.dataset.theme = theme;
    localStorage.setItem('sinaxa-theme', theme);
    if (!toggle) return;
    const target = theme === 'dark' ? 'light' : 'dark';
    toggle.innerHTML = `<i aria-hidden="true">${theme === 'dark' ? '☀' : '☾'}</i>`;
    toggle.title = `Switch to ${target} theme`;
    toggle.setAttribute('aria-label', toggle.title);
  }

  applyTheme(localStorage.getItem('sinaxa-theme') || 'dark');
  if (toggle) toggle.addEventListener('click', () => {
    applyTheme(root.dataset.theme === 'dark' ? 'light' : 'dark');
  });

  const projectList = document.querySelector('[data-project-list]');
  if (projectList) fetch('/api/state').then(response => response.json()).then(data => {
    projectList.innerHTML = (data.projects || []).map(project => {
      const name = String(project.name || '').replace(/[&<>]/g, character => (
        {'&': '&amp;', '<': '&lt;', '>': '&gt;'}[character]
      ));
      return `<a class="project" href="/projects.html"><span><i class="dot ${project.state}"></i>${name}</span><small>${project.state}</small></a>`;
    }).join('');
  }).catch(() => {});
})();
