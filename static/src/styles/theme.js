(function() {
  const STORAGE_KEY = 'suenplayer-theme-v2';
  const VALID_THEMES = ['light', 'dark', 'auto'];

  function getSavedTheme() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw && VALID_THEMES.includes(raw)) return raw;
    } catch (e) {}
    // 旧版 key 兼容（仅迁移一次）
    try {
      const legacy = localStorage.getItem('suenplayer-theme')
        || localStorage.getItem('theme')
        || localStorage.getItem('suenav-theme');
      if (legacy === 'light') return 'light';
      if (legacy === 'dark') return 'dark';
    } catch (e) {}
    return 'auto';
  }

  function applyTheme(theme) {
    const html = document.documentElement;
    html.removeAttribute('data-theme');
    html.classList.remove('light');

    if (theme === 'light') {
      html.setAttribute('data-theme', 'light');
      html.classList.add('light');
      html.style.backgroundColor = '#e0e5ec';
    } else if (theme === 'dark') {
      html.setAttribute('data-theme', 'dark');
      html.style.backgroundColor = '#2d3436';
    } else {
      // auto: 由 prefers-color-scheme 接管
      const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
      html.style.backgroundColor = prefersDark ? '#2d3436' : '#e0e5ec';
    }
  }

  const saved = getSavedTheme();
  applyTheme(saved);

  // 监听系统主题变化（仅在 auto 模式时生效）
  if (window.matchMedia) {
    const mql = window.matchMedia('(prefers-color-scheme: dark)');
    mql.addEventListener('change', function(e) {
      const current = window.__THEME__ ? window.__THEME__.get() : 'auto';
      if (current === 'auto') {
        document.documentElement.style.backgroundColor = e.matches ? '#2d3436' : '#e0e5ec';
      }
    });
  }

  window.__THEME__ = {
    get: () => {
      try { return localStorage.getItem(STORAGE_KEY) || 'auto'; } catch (e) { return 'auto'; }
    },
    set: (theme) => {
      if (!VALID_THEMES.includes(theme)) return;
      try { localStorage.setItem(STORAGE_KEY, theme); } catch (e) {}
      applyTheme(theme);
    },
    toggle: () => {
      const current = window.__THEME__.get();
      const next = current === 'light' ? 'dark' : current === 'dark' ? 'auto' : 'light';
      window.__THEME__.set(next);
      return next;
    },
    apply: applyTheme
  };
})();
