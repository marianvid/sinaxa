(() => {
  const root = document.documentElement;
  const toggle = document.getElementById('themeToggle');
  const icons = {
    sun: '<svg class="theme-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.66 6.34l1.41-1.41"></path></svg>',
    moon: '<svg class="theme-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>'
  };

  function applyTheme(theme) {
    root.dataset.theme = theme;
    localStorage.setItem('sinaxa-theme', theme);
    if (!toggle) return;
    const target = theme === 'dark' ? 'light' : 'dark';
    toggle.innerHTML = theme === 'dark' ? icons.sun : icons.moon;
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
