/* Before CSS: avoid a light flash when a dark preference is saved. */
(function () {
  var choice = 'system';
  try { choice = localStorage.getItem('hackflow-theme') || 'system'; } catch (_) {}
  if (!['light', 'dark', 'system'].includes(choice)) choice = 'system';
  var dark = choice === 'dark' || (choice === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  document.documentElement.dataset.themeChoice = choice;
})();
