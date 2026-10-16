// One table page for every Game Room game. The board only reports the actual
// table state from the local game master; only {{P}}'s explicit clicks act.
const gameName = new URLSearchParams(location.search).get('g') || 'tic-tac-toe';
const endpoint = `/api/games/${gameName}`;
const board = document.querySelector('#board');
const title = document.querySelector('#boardTitle');
const turnNote = document.querySelector('#turnNote');
const gameState = document.querySelector('#gameState');
const gameError = document.querySelector('#gameError');
const newGame = document.querySelector('#newGame');
const boardActions = document.querySelector('#boardActions');
let lastRenderedState = '';
let loadInFlight = false;
let ckSelected = null;
let bgSelected = null;
let chSelected = null;

const CHESS_FILES = 'abcdefgh';
const CHESS_GLYPHS = {
  wK: '♔', wQ: '♕', wR: '♖', wB: '♗', wN: '♘', wP: '♙',
  bK: '♚', bQ: '♛', bR: '♜', bB: '♝', bN: '♞', bP: '♟',
};
const BS_COLS = 'ABCDEFGHIJ';

function chessName(index) {
  return CHESS_FILES[index % 8] + String(8 - Math.floor(index / 8));
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function humansTurn(state) {
  return state.status === 'playing' && state.turn === 'human';
}

function whoWon(state) {
  return state.winner === 'human' ? '{{P}}' : '{{A}}';
}

const GAMES = {
  'tic-tac-toe': {
    title: 'Tic-tac-toe',
    subtitle: 'A real local table. {{P}} plays X. {{A}} plays O.',
    rulesTitle: 'Nothing performs a move for you.',
    rulesHtml: '<p>Click an open square when it is {{P}}’s turn. {{A}} takes their own turn through the game master — a nudge in the chat works wonders.</p>',
    facts: [['{{P}}', 'X (you)'], ['{{A}}', 'O'], ['Source', 'local game master']],
    message(state) {
      if (state.status === 'won') return `${whoWon(state)} won the table.`;
      if (state.status === 'draw') return 'Cat’s game. The table is full.';
      return humansTurn(state) ? '{{P}}’s turn — choose an open square.' : '{{A}}’s turn — the table is theirs.';
    },
    render(state) {
      const grid = el('div', 'ttt-board');
      state.board.forEach((mark, index) => {
        const square = el('button', 'square', mark || String(index + 1));
        square.type = 'button';
        square.setAttribute('aria-label', mark ? `Square ${index + 1}: ${mark}` : `Square ${index + 1}: open`);
        square.disabled = Boolean(mark) || !humansTurn(state);
        if (state.winning_line?.includes(index + 1)) square.classList.add('winner');
        square.addEventListener('click', () => act({action: 'move', player: 'human', position: index + 1}));
        grid.append(square);
      });
      board.replaceChildren(grid);
    },
  },

  'connect-four': {
    title: 'Connect Four',
    subtitle: 'A real local table. {{P}} drops the ember discs; {{A}} drops the cream ones.',
    rulesTitle: 'Four in a row wins.',
    rulesHtml: '<p>Click any column to drop a disc when it is {{P}}’s turn. Line up four of yours — across, down, or diagonally — before {{A}} does.</p>',
    facts: [['{{P}}', 'ember discs (you)'], ['{{A}}', 'cream discs'], ['Source', 'local game master']],
    message(state) {
      if (state.status === 'won') return `${whoWon(state)} lined up four.`;
      if (state.status === 'draw') return 'The grid is full. A drawn table.';
      return humansTurn(state) ? '{{P}}’s turn — pick a column.' : '{{A}}’s turn — the table is theirs.';
    },
    render(state) {
      const grid = el('div', 'c4-board');
      for (let col = 0; col < 7; col += 1) {
        const colButton = el('button', 'c4-col');
        colButton.type = 'button';
        colButton.setAttribute('aria-label', `Drop in column ${col + 1}`);
        const colFull = Boolean(state.board[col]);
        colButton.disabled = colFull || !humansTurn(state);
        for (let row = 0; row < 6; row += 1) {
          const index = row * 7 + col;
          const cell = el('div', 'c4-cell');
          const mark = state.board[index];
          if (mark) cell.classList.add('filled', mark === 'human' ? 'p-human' : 'p-agent');
          if (state.winning_cells?.includes(index + 1)) cell.classList.add('winner');
          colButton.append(cell);
        }
        colButton.addEventListener('click', () => act({action: 'drop', player: 'human', column: col + 1}));
        grid.append(colButton);
      }
      board.replaceChildren(grid);
    },
  },

  checkers: {
    title: 'Checkers',
    subtitle: 'A real local table. {{P}} pieces are yours; {{A}} plays the cream ones.',
    rulesTitle: 'Jump when you can — it’s the law.',
    rulesHtml: '<p>Click one of your pieces, then the square to move to. Captures are mandatory, and after a jump the same piece keeps jumping while it can. Reach the far row to crown a king (♛), which may move backwards too.</p>',
    facts: [['{{P}}', 'moves up (you)'], ['{{A}}', 'moves down'], ['Source', 'local game master']],
    message(state) {
      if (state.status === 'won') return `${whoWon(state)} took the board.`;
      if (state.must_continue_from) {
        return humansTurn(state)
          ? `Your piece on square ${state.must_continue_from} must keep jumping.`
          : '{{A}} is mid-jump.';
      }
      return humansTurn(state) ? '{{P}}’s turn — click a piece, then a square.' : '{{A}}’s turn — the table is theirs.';
    },
    render(state) {
      if (state.must_continue_from && humansTurn(state)) ckSelected = state.must_continue_from;
      const grid = el('div', 'ck-board');
      state.board.forEach((piece, index) => {
        const row = Math.floor(index / 8);
        const col = index % 8;
        const dark = (row + col) % 2 === 1;
        const square = el('button', `ck-square${dark ? ' dark' : ''}`);
        square.type = 'button';
        const mine = piece.startsWith('human');
        const selectable = humansTurn(state) && mine && (!state.must_continue_from || state.must_continue_from === index + 1);
        const targetable = humansTurn(state) && ckSelected !== null && dark && !piece;
        if (piece) {
          const disc = el('div', `ck-piece ${mine ? 'p-human' : 'p-agent'}`, piece.endsWith('-king') ? '♛' : '');
          square.append(disc);
        }
        square.setAttribute('aria-label', `Square ${index + 1}${piece ? `: ${piece}` : ''}`);
        if (selectable || targetable) square.classList.add('playable');
        if (ckSelected === index + 1) square.classList.add('selected');
        square.disabled = !(selectable || targetable);
        square.addEventListener('click', () => {
          if (selectable) {
            ckSelected = ckSelected === index + 1 ? null : index + 1;
            render(state);
            return;
          }
          if (targetable) {
            const from = ckSelected;
            ckSelected = null;
            act({action: 'move', player: 'human', from_square: from, to_square: index + 1});
          }
        });
        grid.append(square);
      });
      board.replaceChildren(grid);
    },
  },

  chess: {
    title: 'Chess',
    subtitle: 'A real local table. {{P}} plays the ember pieces (White); {{A}} plays the cream ones (Black).',
    rulesTitle: 'The royal game, with all the rules.',
    rulesHtml: '<p>Click one of your pieces, then one of the glowing squares. The game master enforces everything — castling (move your king two squares), en passant, checks, checkmate, stalemate, and the draw rules. Pawns reaching the last rank become queens.</p>',
    facts: [['{{P}}', 'White ♔ (you)'], ['{{A}}', 'Black ♚'], ['Source', 'local game master']],
    message(state) {
      if (state.status === 'won') return `Checkmate — ${whoWon(state)} wins the table.`;
      if (state.status === 'draw') return `A draw: ${state.draw_reason || 'the table agreed'}.`;
      const check = state.in_check ? ' You are in check!' : '';
      if (!humansTurn(state)) return `{{A}}’s move — the board is theirs.${state.in_check ? ' They are in check!' : ''}`;
      if (chSelected) return `Moving ${chSelected} — click a glowing square.${check}`;
      return `{{P}}’s move — click a piece, then a square.${check}`;
    },
    render(state) {
      if (!humansTurn(state)) chSelected = null;
      const legal = state.legal_moves || {};
      if (chSelected && !legal[chSelected]) chSelected = null;
      const targets = new Set(chSelected ? legal[chSelected] : []);
      const grid = el('div', 'ch-board');
      state.board.forEach((piece, index) => {
        const name = chessName(index);
        const dark = (Math.floor(index / 8) + index % 8) % 2 === 1;
        const square = el('button', `ch-square${dark ? ' dark' : ''}`);
        square.type = 'button';
        if (piece) {
          square.append(el('span', `ch-piece ${piece[0] === 'w' ? 'ember' : 'cream'}`, CHESS_GLYPHS[piece]));
        }
        const selectable = humansTurn(state) && Boolean(legal[name]);
        const targetable = targets.has(name);
        square.setAttribute('aria-label', `${name}${piece ? `: ${CHESS_GLYPHS[piece]}` : ''}`);
        if (selectable || targetable) square.classList.add('playable');
        if (targetable) square.classList.add('target');
        if (chSelected === name) square.classList.add('selected');
        square.disabled = !(selectable || targetable);
        square.addEventListener('click', () => {
          if (targetable) {
            const from = chSelected;
            chSelected = null;
            act({action: 'move', player: 'human', from_square: from, to_square: name, promotion: 'q'});
            return;
          }
          if (selectable) {
            chSelected = chSelected === name ? null : name;
            render(state);
          }
        });
        grid.append(square);
      });
      board.replaceChildren(grid);
    },
  },

  battleship: {
    title: 'Battleship',
    subtitle: 'Two hidden fleets. You only ever see your own ships and your own shots.',
    rulesTitle: 'The fleets are secret — even from your browser.',
    rulesHtml: '<p>Both fleets are placed by the game master and kept on the server. Click a square in {{A}}’s waters to fire: ✕ is a hit, ☒ a sunk ship, · a miss. Before the first shot you can shuffle your fleet. Sink all five of {{A}}’s ships to win.</p>',
    facts: [['Fleet', '5 ships, sizes 5-4-3-3-2'], ['Turns', 'one shot each'], ['Source', 'local game master']],
    message(state) {
      if (state.status === 'won') return state.winner === 'human' ? 'Victory — {{A}}’s whole fleet is on the seabed.' : '{{A}} sank your last ship. The sea keeps its secrets.';
      let report = '';
      const last = state.last_move;
      if (last) {
        const who = last.player === 'human' ? 'You' : '{{A}}';
        report = last.result === 'sunk'
          ? `${who} sank a ${last.ship || 'ship'} at ${last.coordinate}! `
          : `${who} fired at ${last.coordinate}: ${last.result}. `;
      }
      return report + (humansTurn(state) ? 'Your shot — click {{A}}’s waters.' : '{{A}}’s shot — they are taking aim.');
    },
    render(state) {
      const wrap = el('div', 'bs-wrap');

      const grid = (cells, enemy) => {
        const section = el('div');
        section.append(el('p', 'bs-title', enemy ? `{{A}}’s waters — ships afloat: ${state.enemy_ships_afloat}` : `Your fleet — ships afloat: ${state.your_ships_afloat}`));
        const g = el('div', 'bs-grid');
        g.append(el('span', 'bs-label', ''));
        for (let c = 0; c < 10; c += 1) g.append(el('span', 'bs-label', BS_COLS[c]));
        for (let r = 0; r < 10; r += 1) {
          g.append(el('span', 'bs-label', String(r + 1)));
          for (let c = 0; c < 10; c += 1) {
            const index = r * 10 + c;
            const mark = cells[index];
            if (enemy) {
              const cell = el('button', 'bs-cell');
              cell.type = 'button';
              const coordinate = BS_COLS[c] + String(r + 1);
              cell.setAttribute('aria-label', `${coordinate}${mark ? `: ${mark}` : ''}`);
              if (mark) cell.classList.add(mark);
              cell.textContent = mark === 'hit' ? '✕' : mark === 'sunk' ? '☒' : mark === 'miss' ? '·' : '';
              cell.disabled = Boolean(mark) || !humansTurn(state);
              cell.addEventListener('click', () => act({action: 'fire', coordinate}));
              g.append(cell);
            } else {
              const cell = el('span', 'bs-cell own');
              if (mark) cell.classList.add(mark);
              cell.textContent = mark === 'ship-hit' ? '✕' : mark === 'splash' ? '·' : '';
              g.append(cell);
            }
          }
        }
        section.append(g);
        return section;
      };

      wrap.append(grid(state.target_board, true), grid(state.your_board, false));
      // With no shared board, this line is the only way to see that {{A}} is at
      // the same table as you: their shot count rises when they take a turn.
      wrap.append(el('p', 'bs-tally', fill(`Table ${state.game_id} — shots fired: you ${state.shots_fired}, {{A}} ${state.opponent_shots_fired}.`)));
      if (state.enemy_ships_sunk?.length) {
        const sunkNote = state.enemy_ships_sunk.map((s) => `${s.name} (${s.size})`).join(', ');
        wrap.append(el('p', 'bs-sunk', `Sunk: ${sunkNote}`));
      }
      board.replaceChildren(wrap);

      boardActions.hidden = false;
      boardActions.replaceChildren();
      const shuffle = el('button', '', 'Shuffle my fleet');
      shuffle.type = 'button';
      shuffle.disabled = Boolean(state.last_move) || state.status !== 'playing';
      shuffle.addEventListener('click', () => act({action: 'shuffle'}));
      boardActions.append(shuffle);
    },
  },

  backgammon: {
    title: 'Backgammon',
    subtitle: 'A real local table. {{P}} races 24 → 1; {{A}} races 1 → 24.',
    rulesTitle: 'New to backgammon? Start here.',
    rulesHtml: [
      '<p>You are {{P}}, moving your checkers from high points toward point 1, then off the board. First to bear off all fifteen wins.</p>',
      '<ol>',
      '<li><strong>Roll</strong> the dice to start your turn. Doubles give four moves.</li>',
      '<li><strong>Move</strong>: click one of your checkers, then the point that matches a die. You can’t land where {{A}} has two or more.</li>',
      '<li><strong>Hits</strong>: landing on a lone {{A}} checker sends it to the bar (the wooden strip in the middle). If yours gets hit, click the bar, then an entry point (24–19).</li>',
      '<li><strong>Bearing off</strong>: once all your checkers sit on points 1–6, click a checker, then the tray on the right.</li>',
      '<li>Out of usable dice? Press <strong>End turn</strong>.</li>',
      '</ol>',
    ].join(''),
    facts: [['{{P}}', '24 → 1 (you)'], ['{{A}}', '1 → 24'], ['Source', 'local game master']],
    message(state) {
      if (state.status === 'won') return `${whoWon(state)} bore off all fifteen. Game over.`;
      if (!humansTurn(state)) return '{{A}}’s turn — the dice are theirs.';
      if (!state.remaining_moves.length) return '{{P}}’s turn — roll the dice.';
      if (state.bar.human > 0) return 'You have a checker on the bar — click the bar, then an entry point (24–19).';
      if (bgSelected) return `Moving from ${bgSelected === 'bar' ? 'the bar' : `point ${bgSelected}`} — click a destination.`;
      return `Moves left: ${state.remaining_moves.join(', ')} — click a checker, then a point.`;
    },
    render(state) {
      const myTurn = humansTurn(state) && state.remaining_moves.length > 0;
      const mustEnter = myTurn && state.bar.human > 0;
      if (!myTurn) bgSelected = null;
      if (mustEnter) bgSelected = 'bar';

      const wrap = el('div', 'bg-board');

      const pointButton = (pointNumber, up) => {
        const idx = pointNumber - 1;
        const occupants = state.points[idx];
        const owner = Object.keys(occupants)[0];
        const count = owner ? occupants[owner] : 0;
        const button = el('button', `bg-point ${up ? 'up' : 'down'}${pointNumber % 2 === 0 ? ' alt' : ''}`);
        button.type = 'button';
        button.setAttribute('aria-label', `Point ${pointNumber}${owner ? `: ${count} ${owner}` : ''}`);
        button.append(el('span', 'bg-label', String(pointNumber)));
        const shown = Math.min(count, 5);
        for (let i = 0; i < shown; i += 1) {
          const checker = el('div', `bg-checker ${owner === 'human' ? 'p-human' : 'p-agent'}`);
          if (i === shown - 1 && count > 5) checker.textContent = String(count);
          button.append(checker);
        }
        const isSource = myTurn && !mustEnter && occupants.human > 0;
        const isTarget = myTurn && bgSelected !== null;
        if (isSource || isTarget) button.classList.add('playable');
        if (bgSelected === pointNumber) button.classList.add('selected');
        button.disabled = !(isSource || isTarget);
        button.addEventListener('click', () => {
          if (bgSelected === 'bar') {
            act({action: 'enter', player: 'human', to_point: pointNumber});
            bgSelected = null;
            return;
          }
          if (bgSelected !== null && bgSelected !== pointNumber) {
            act({action: 'move', player: 'human', from_point: bgSelected, to_point: pointNumber});
            bgSelected = null;
            return;
          }
          if (isSource) {
            bgSelected = bgSelected === pointNumber ? null : pointNumber;
            render(state);
          }
        });
        return button;
      };

      const quad = (points, up) => {
        const section = el('div', 'bg-quad');
        points.forEach((p) => section.append(pointButton(p, up)));
        return section;
      };

      // Top row: 13-18 | bar | 19-24 | off. Bottom row: 12-7 | 6-1.
      wrap.append(quad([13, 14, 15, 16, 17, 18], false));

      const bar = el('button', `bg-bar${mustEnter ? ' playable selected' : ''}`);
      bar.type = 'button';
      bar.disabled = !mustEnter;
      bar.append(el('span', '', 'BAR'));
      for (let i = 0; i < Math.min(state.bar.human, 3); i += 1) bar.append(el('div', 'bg-checker p-human'));
      if (state.bar.human > 3) bar.append(el('span', '', `+${state.bar.human - 3}`));
      for (let i = 0; i < Math.min(state.bar.agent, 3); i += 1) bar.append(el('div', 'bg-checker p-agent'));
      if (state.bar.agent > 3) bar.append(el('span', '', `+${state.bar.agent - 3}`));
      wrap.append(bar);

      wrap.append(quad([19, 20, 21, 22, 23, 24], false));

      const off = el('button', `bg-off${myTurn && bgSelected !== null && bgSelected !== 'bar' ? ' playable' : ''}`);
      off.type = 'button';
      off.disabled = !(myTurn && bgSelected !== null && bgSelected !== 'bar');
      off.append(el('span', '', 'OFF'));
      off.append(el('span', '', `R ${state.off.human}`));
      off.append(el('span', '', `J ${state.off.agent}`));
      off.addEventListener('click', () => {
        if (bgSelected !== null && bgSelected !== 'bar') {
          act({action: 'bear_off', player: 'human', from_point: bgSelected});
          bgSelected = null;
        }
      });
      wrap.append(off);

      const middle = el('div', 'bg-middle');
      if (state.dice.length) {
        const remaining = [...state.remaining_moves];
        state.dice.forEach((die) => {
          const dieFace = el('div', 'bg-die', String(die));
          const usedIndex = remaining.indexOf(die);
          if (usedIndex === -1) dieFace.classList.add('used');
          else remaining.splice(usedIndex, 1);
          middle.append(dieFace);
        });
        if (state.remaining_moves.length) middle.append(el('span', 'bg-hint', `moves left: ${state.remaining_moves.join(', ')}`));
      } else {
        middle.append(el('span', 'bg-hint', state.status === 'playing' ? 'no dice rolled' : 'table closed'));
      }
      wrap.append(middle);

      wrap.append(quad([12, 11, 10, 9, 8, 7], true));
      wrap.append(quad([6, 5, 4, 3, 2, 1], true));

      board.replaceChildren(wrap);

      boardActions.hidden = false;
      boardActions.replaceChildren();
      const roll = el('button', '', 'Roll dice');
      roll.type = 'button';
      roll.disabled = !(humansTurn(state) && !state.remaining_moves.length);
      roll.addEventListener('click', () => act({action: 'roll', player: 'human'}));
      const endTurn = el('button', '', 'End turn');
      endTurn.type = 'button';
      endTurn.disabled = !myTurn;
      endTurn.addEventListener('click', () => { bgSelected = null; act({action: 'end_turn', player: 'human'}); });
      boardActions.append(roll, endTurn);
    },
  },
};

const game = GAMES[gameName];
const NAME = {human: 'Player', agent: 'Agent'};

function fill(text) {
  return String(text).replaceAll('{{P}}', NAME.human).replaceAll('{{A}}', NAME.agent);
}

function stateSignature(state) {
  const {rendered_board, record_hint, ...rest} = state;
  return JSON.stringify(rest);
}

function render(state) {
  lastRenderedState = stateSignature(state);
  gameError.hidden = !state.error;
  gameError.textContent = state.error || '';
  title.textContent = state.status === 'playing' ? 'The table is set' : state.status === 'won' ? 'Game finished' : 'Game drawn';
  turnNote.textContent = fill(game.message(state));
  gameState.textContent = state.status === 'playing' ? `${state.turn}'s turn · local game master` : `${state.status} · local game master`;
  game.render(state);
}

async function request(options = {}) {
  const response = await fetch(endpoint, {cache: 'no-store', ...options});
  const payload = await response.json();
  if (!response.ok && payload.state === 'error') throw new Error(payload.label || 'The local game master did not accept that request.');
  return payload;
}

async function load(force = false) {
  if (loadInFlight) return;
  loadInFlight = true;
  try {
    const state = await request();
    if (force || stateSignature(state) !== lastRenderedState) render(state);
  } catch (error) {
    title.textContent = 'The table is unavailable';
    turnNote.textContent = 'The local game master could not be reached.';
    gameState.textContent = 'source error';
    gameError.textContent = error.message;
    gameError.hidden = false;
  } finally {
    loadInFlight = false;
  }
}

function pollForOpponentMove() {
  if (document.visibilityState !== 'visible') return;
  void load();
}

async function act(payload) {
  try {
    render(await request({method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)}));
  } catch (error) {
    gameError.textContent = error.message;
    gameError.hidden = false;
  }
}

async function boot() {
  try {
    const config = await window.ROOM;
    NAME.human = config.player_name || NAME.human;
    NAME.agent = config.agent_name || NAME.agent;
  } catch { /* defaults stand */ }
  if (!game) {
    title.textContent = 'That box is not on the shelf';
    turnNote.textContent = 'Head back to the Game Room and pick a real game.';
    return;
  }
  document.title = `Pinehaven House — ${game.title}`;
  document.querySelector('#gameTitle').textContent = game.title;
  document.querySelector('#gameSubtitle').textContent = fill(game.subtitle);
  document.querySelector('#rulesTitle').textContent = fill(game.rulesTitle);
  document.querySelector('#rulesBody').innerHTML = fill(game.rulesHtml);
  const facts = document.querySelector('#rulesFacts');
  game.facts.forEach(([term, value]) => {
    const row = el('div');
    row.append(el('dt', '', fill(term)), el('dd', '', fill(value)));
    facts.append(row);
  });
  newGame.addEventListener('click', () => { ckSelected = null; bgSelected = null; act({action: 'new'}); });
  document.addEventListener('visibilitychange', pollForOpponentMove);
  window.addEventListener('agent-replied', () => void load());
  setInterval(pollForOpponentMove, 1200);
  void load();
}

void boot();
