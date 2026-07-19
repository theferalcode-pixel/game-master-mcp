// Shared room configuration: display names, chat availability, and the theme.
// The theme applies immediately from localStorage so pages never flash, then
// the server default fills in for first-time visitors.
(() => {
  const THEMES = ['hearth', 'tide', 'grove'];
  const saved = localStorage.getItem('gameroom-theme');
  if (THEMES.includes(saved)) document.documentElement.dataset.theme = saved;

  window.ROOM = fetch('/api/config', {cache: 'no-store'})
    .then((response) => response.json())
    .then((config) => {
      if (!saved && THEMES.includes(config.theme)) {
        document.documentElement.dataset.theme = config.theme;
      }
      return config;
    })
    .catch(() => ({player_name: 'Player', agent_name: 'Agent', theme: 'hearth', chat_enabled: false}));

  window.addEventListener('DOMContentLoaded', () => {
    const picker = document.querySelector('#themePick');
    if (!picker) return;
    picker.value = document.documentElement.dataset.theme || 'hearth';
    void window.ROOM.then(() => {
      picker.value = document.documentElement.dataset.theme || 'hearth';
    });
    picker.addEventListener('change', () => {
      document.documentElement.dataset.theme = picker.value;
      localStorage.setItem('gameroom-theme', picker.value);
    });
  });
})();
