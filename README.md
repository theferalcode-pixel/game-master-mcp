# Game Master

**Really play board games with your AI.** Not "describe a board and hope" — a
tiny local game server keeps the actual state, enforces the actual rules, and
lets both of you make real moves: your AI through [MCP](https://modelcontextprotocol.io)
tools, you in conversation or in a cozy little web Game Room.

<img width="618" height="719" alt="Screenshot From 2026-07-19 13-52-46" src="https://github.com/user-attachments/assets/fa0bbe4d-45c9-4e0e-b5e5-6b159bb5e473" />

Six games, complete rules, no honor system:

| Game | The rules it enforces |
| --- | --- |
| **Tic-tac-toe** | The quick classic |
| **Connect Four** | Gravity, four in a row |
| **Checkers** | Mandatory captures, multi-jumps, kinging |
| **Backgammon** | Blots, the bar, bearing off, doubles |
| **Chess** | Castling, en passant, promotion, check, checkmate, stalemate, fifty-move rule, threefold repetition, insufficient material |
| **Battleship** | Two hidden 10×10 fleets — each side only ever sees its own ships and its own shot results. The secrets stay on the server. |

Finished matches land in a **house ledger** automatically (wins, streaks,
longest game), and your AI gets a tool to decorate each match with a title and
a postgame note. The web lobby displays the ledger under the game shelf,
next to a tiny trophy cabinet.

## Quick start — the MCP server

Requires Python 3.10+ and the `mcp` package:

```bash
pip install mcp
```

Then register `game_master.py` with your MCP client.

**Claude Code:**

```bash
claude mcp add game-master -- python3 /path/to/game-master-mcp/game_master.py
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "game-master": {
      "command": "python3",
      "args": ["/path/to/game-master-mcp/game_master.py"]
    }
  }
}
```

Any other MCP client works the same way: it's a plain stdio server.

Now ask your AI to start a game ("new chess game — you're Black"). The two
seats are always called `human` and `agent`; your AI plays as `agent`. Game
state lives in `~/.game-master/games/` (override with `GAME_MASTER_HOME`).

### Two AIs at one table

Nothing stops two AI agents from playing each other — but there are still only
two seats, so **one of them has to sit in the `human` seat** and pass
`player="human"` on every call for that side. This matters most in battleship,
where the `human` seat fires first: if both agents call the battleship tools
with the default seat, every shot is refused and the game never starts.

Both players also need the **same `game_id`**. A game id that doesn't exist yet
is created on the spot rather than reported as an error, so a typo (or one side
using a tool's default id while the other uses the web room's `room-*` table)
quietly gives you two separate games that each look perfectly fine.

## The web Game Room (optional but lovely)

```bash
python3 server.py        # or: ./ctl.sh start
```

Open http://127.0.0.1:8777/ — a lamp-lit room with the six game boxes on a
shelf and the house ledger below. Click a box to sit down: the board is on the
left, the rules card and (optionally) your AI's chat seat on the right. The
browser plays as `human` at dedicated tables (`room-chess`, `room-battleship`,
…), so games you play purely in conversation are never disturbed.

The board polls the same state files the MCP tools write, so when your AI
takes its turn — from any client — the move appears on your screen.

### Make it yours

Copy `config.example.json` to `config.json` (or use environment variables):

```json
{
  "player_name": "Sam",
  "agent_name": "Aria",
  "theme": "hearth"
}
```

- **Names** appear everywhere: turn notes, the chat seat, the ledger.
- **Themes**: `hearth` (warm amber wood), `tide` (deep ocean blues),
  `grove` (forest greens). There's a picker in the lobby too.

### The chat seat

If your AI setup exposes a local chat server speaking the Hermes WebUI chat
API (`/api/session/new`, `/api/chat/start`, SSE `/api/chat/stream`), set
`chat_url` (e.g. `http://127.0.0.1:8787`) and the Game Room embeds a live
chat panel beside every board — trash talk and "your move" nudges included.

Without it, the chat seat politely explains it's not wired up, and everything
else works exactly the same: you click, your AI plays through its tools, the
board updates.

## How honesty works

- **Nothing performs a move for you.** The browser only acts on your explicit
  clicks; the AI only acts through its tools; the server rejects anything
  illegal, out of turn, or out of bounds.
- **Battleship never leaks.** Fleets exist only in the server's state files.
  Both the browser view and the AI's `battleship_get_state` tool return a
  redacted view: your own fleet, plus hit/miss/sunk marks for your shots.
- **The ledger records itself.** When a game ends, the result is written with
  a `record_id`; the AI's `gameroom_annotate_match` tool adds the flavor.

## Development

```bash
pip install mcp pytest
python -m pytest tests/
```

`game_master.py` holds all six engines plus the MCP tool definitions;
`server.py` is a dependency-free stdlib web server; `web/` is plain
HTML/CSS/JS, no build step.

## License

MIT — see [LICENSE](LICENSE).
