try {
  const selectedTheme = localStorage.getItem('oiltech-theme');
  document.documentElement.dataset.theme = ['light', 'dusk', 'dark'].includes(selectedTheme) ? selectedTheme : 'light';
} catch (_) {
  document.documentElement.dataset.theme = 'light';
}
