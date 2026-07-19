// The House Records ledger. Read-only: the game master writes results when
// games actually finish, and Agent supplies titles through his own tools.
(async () => {
  const NAME = {human: 'Player', agent: 'Agent'};
  try {
    const config = await window.ROOM;
    NAME.human = config.player_name || NAME.human;
    NAME.agent = config.agent_name || NAME.agent;
  } catch { /* defaults stand */ }
  const statsBox = document.querySelector('#recordsStats');
  const table = document.querySelector('#recordsTable');
  const list = document.querySelector('#recordsList');
  const badge = document.querySelector('#recordsState');

  

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function stat(label, value) {
    const box = el('div', 'stat');
    box.append(el('strong', '', value), el('span', '', label));
    return box;
  }

  function summaryFor(record) {
    const moves = record.moves ? ` in ${record.moves} moves` : '';
    if (record.result === 'draw') return `${record.game} — a draw${moves}`;
    const winner = record.winner === 'human' ? NAME.human : NAME.agent;
    const loser = record.winner === 'human' ? NAME.agent : NAME.human;
    return `${record.game} — ${winner} defeated ${loser}${moves}`;
  }

  async function load() {
    try {
      const response = await fetch('/api/gameroom/records', {cache: 'no-store'});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.label || 'Ledger unavailable');
      const stats = payload.stats || {};
      const score = stats.score || {human: 0, agent: 0, draws: 0};

      statsBox.replaceChildren(
        stat(`all-time ${NAME.human} vs. ${NAME.agent}`, `${score.human} – ${score.agent}`),
        stat('draws', String(score.draws)),
        stat('current streak', stats.streak?.player
          ? `${stats.streak.player === 'human' ? NAME.human : NAME.agent} × ${stats.streak.count}`
          : '—'),
        stat('longest game', stats.longest
          ? `${stats.longest.game} · ${stats.longest.moves} moves`
          : '—'),
        stat('matches played', String(stats.total_matches || 0)),
      );

      table.replaceChildren();
      const head = el('tr');
      ['Game', NAME.human, NAME.agent, 'Draws'].forEach((h) => head.append(el('th', '', h)));
      table.append(head);
      const perGame = stats.per_game || {};
      Object.keys(perGame).sort().forEach((game) => {
        const tally = perGame[game];
        const row = el('tr');
        row.append(el('td', '', game), el('td', '', String(tally.human)),
          el('td', '', String(tally.agent)), el('td', '', String(tally.draws)));
        table.append(row);
      });
      if (Object.keys(perGame).length === 0) {
        const row = el('tr');
        const cell = el('td', 'records-empty', 'No finished games yet. The shelf is waiting.');
        cell.colSpan = 4;
        row.append(cell);
        table.append(row);
      }

      list.replaceChildren();
      const records = (payload.records || []).slice(0, 8);
      if (!records.length) {
        list.append(el('li', 'records-empty', 'Finish a game and it will be written up here.'));
      }
      records.forEach((record) => {
        const item = el('li', 'record-item');
        item.append(el('strong', '', record.title || summaryFor(record)));
        if (record.title) item.append(el('span', 'record-summary', summaryFor(record)));
        if (record.note) item.append(el('em', 'record-note', record.note));
        item.append(el('span', 'record-when', (record.finished_at || '').slice(0, 10)));
        list.append(item);
      });

      badge.textContent = payload.state === 'empty' ? 'ledger open · no entries yet' : 'live · house ledger';
    } catch (error) {
      badge.textContent = 'ledger unavailable';
      statsBox.replaceChildren(el('p', 'records-empty', error.message));
    }
  }

  void load();
})();
