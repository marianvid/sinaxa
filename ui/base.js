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
})();
