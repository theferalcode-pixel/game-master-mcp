"""Game Master — an MCP server for really playing board games with your AI.

Six games (tic-tac-toe, Connect Four, checkers, backgammon, chess, battleship)
with the rules enforced by this server, not by anyone's honor system. Both
players act through the same tiny state files: the AI through MCP tools, the
human either in conversation or through the bundled web Game Room (server.py).

The two seats are called "human" and "agent". Finished matches land in a house
ledger the AI can decorate with titles and postgame notes.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

FastMCP: Any
try:  # pragma: no cover - exercised by import flag tests / runtime smoke tests
    from mcp.server.fastmcp import FastMCP as _FastMCP  # type: ignore[reportMissingImports]

    FastMCP = _FastMCP
    _MCP_SERVER_AVAILABLE = True
except ImportError:  # pragma: no cover - mcp extra may not be installed everywhere
    FastMCP = None
    _MCP_SERVER_AVAILABLE = False

logger = logging.getLogger(__name__)

EMPTY = ""
PLAYERS = {"human": "X", "agent": "O"}
WINNING_LINES = (
    (0, 1, 2),
    (3, 4, 5),
    (6, 7, 8),
    (0, 3, 6),
    (1, 4, 7),
    (2, 5, 8),
    (0, 4, 8),
    (2, 4, 6),
)


def _data_home() -> Path:
    return Path(os.environ.get("GAME_MASTER_HOME", Path.home() / ".game-master"))


def _games_dir() -> Path:
    path = _data_home() / "games"
    path.mkdir(parents=True, exist_ok=True)
    return path


# Every game has one default table, and it is the same table the web Game Room
# plays at. That way a person can just say "let's play battleship" and their AI
# sits down at the board already on their screen — nobody has to know a table
# has a name. Pass an explicit game_id only to run a second, separate game.
TABLE_TICTACTOE = "room-tictactoe"
TABLE_CONNECT4 = "room-connect4"
TABLE_CHECKERS = "room-checkers"
TABLE_BACKGAMMON = "room-backgammon"
TABLE_CHESS = "room-chess"
TABLE_BATTLESHIP = "room-battleship"


def _normalize_game_id(game_id: str) -> str:
    game_id = (game_id or TABLE_TICTACTOE).strip().lower()
    game_id = re.sub(r"[^a-z0-9_.-]+", "-", game_id).strip("-._")
    return game_id or TABLE_TICTACTOE


def _game_path(game_id: str) -> Path:
    return _games_dir() / f"{_normalize_game_id(game_id)}.json"


def _render_board(board: list[str]) -> str:
    cells = [mark if mark else str(i + 1) for i, mark in enumerate(board)]
    return (
        f"{cells[0]} | {cells[1]} | {cells[2]}\n"
        "--+---+--\n"
        f"{cells[3]} | {cells[4]} | {cells[5]}\n"
        "--+---+--\n"
        f"{cells[6]} | {cells[7]} | {cells[8]}"
    )


def _with_view(state: dict[str, Any]) -> dict[str, Any]:
    state = dict(state)
    state["rendered_board"] = _render_board(state["board"])
    return state


def _save_game(state: dict[str, Any]) -> dict[str, Any]:
    state_to_write = dict(state)
    state_to_write.pop("rendered_board", None)
    _game_path(state_to_write["game_id"]).write_text(
        json.dumps(state_to_write, indent=2, sort_keys=True), encoding="utf-8"
    )
    return _with_view(state_to_write)


def load_game(game_id: str = TABLE_TICTACTOE) -> dict[str, Any]:
    """Load an existing tic-tac-toe game, creating a fresh one if missing."""
    path = _game_path(game_id)
    if not path.exists():
        return new_game(game_id=game_id)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("corrupt game state at %s; starting over", path)
        return new_game(game_id=game_id)
    return _with_view(state)


def new_game(
    game_id: str = TABLE_TICTACTOE,
    human_mark: str = "X",
    agent_mark: str = "O",
) -> dict[str, Any]:
    """Create or reset a tic-tac-toe game."""
    human_mark = (human_mark or "X").strip()[:2] or "X"
    agent_mark = (agent_mark or "O").strip()[:2] or "O"
    state = {
        "game_id": _normalize_game_id(game_id),
        "game": "tic-tac-toe",
        "players": {
            "human": {"mark": human_mark},
            "agent": {"mark": agent_mark},
        },
        "board": [EMPTY] * 9,
        "turn": "human",
        "status": "playing",
        "winner": None,
        "winning_line": None,
        "moves": [],
        "error": None,
    }
    return _save_game(state)


def _mark_for(state: dict[str, Any], player: str) -> str:
    return state.get("players", {}).get(player, {}).get("mark") or PLAYERS[player]


def _evaluate(state: dict[str, Any]) -> None:
    board = state["board"]
    for line in WINNING_LINES:
        a, b, c = line
        if board[a] and board[a] == board[b] == board[c]:
            state["status"] = "won"
            state["winner"] = state["moves"][-1]["player"] if state["moves"] else None
            state["winning_line"] = [i + 1 for i in line]
            return
    if all(board):
        state["status"] = "draw"
        state["winner"] = None
        state["winning_line"] = None


def submit_move(game_id: str = TABLE_TICTACTOE, player: str = "human", position: int = 1) -> dict[str, Any]:
    """Submit a move for Human or Agent.

    Args:
        game_id: Which table to play at; the default is the room's.
        player: human or agent.
        position: Board square 1-9, left-to-right/top-to-bottom.
    """
    state = load_game(game_id)
    state.pop("rendered_board", None)
    state["error"] = None

    player = (player or "").strip().lower()
    if player not in PLAYERS:
        state["error"] = "Player must be human or agent."
        return _with_view(state)

    if state["status"] != "playing":
        state["error"] = (
            f"Game {state['game_id']} is already {state['status']}. "
            "Start a new game to play again."
        )
        return _with_view(state)

    if player != state["turn"]:
        state["error"] = f"It is {state['turn']}'s turn, not {player}'s."
        return _with_view(state)

    try:
        square = int(position)
    except (TypeError, ValueError):
        state["error"] = "Position must be a number from 1 to 9."
        return _with_view(state)

    if square < 1 or square > 9:
        state["error"] = "Position must be a number from 1 to 9."
        return _with_view(state)

    idx = square - 1
    if state["board"][idx]:
        state["error"] = f"Square {square} is already occupied."
        return _with_view(state)

    state["board"][idx] = _mark_for(state, player)
    state["moves"].append({"player": player, "position": square, "mark": state["board"][idx]})
    state["turn"] = "agent" if player == "human" else "human"
    _evaluate(state)
    if state["status"] == "won":
        _record_result(state, f"three in a row on squares {state['winning_line']}")
    elif state["status"] == "draw":
        _record_result(state, "cat's game — the table filled up")
    return _save_game(state)


BACKGAMMON_PLAYERS = {"human", "agent"}


def _backgammon_path(game_id: str) -> Path:
    return _games_dir() / f"{_normalize_game_id(game_id)}.backgammon.json"


def _empty_points() -> list[dict[str, int]]:
    return [{} for _ in range(24)]


def _backgammon_standard_points() -> list[dict[str, int]]:
    """Return standard backgammon setup using point numbers 1-24 as indices 0-23.

    Human moves from point 24 toward point 1. Agent moves from point 1 toward point 24.
    """
    points = _empty_points()
    points[23] = {"human": 2}
    points[12] = {"human": 5}
    points[7] = {"human": 3}
    points[5] = {"human": 5}
    points[0] = {"agent": 2}
    points[11] = {"agent": 5}
    points[16] = {"agent": 3}
    points[18] = {"agent": 5}
    return points


def _backgammon_cell(occupants: dict[str, int]) -> str:
    if not occupants:
        return "·  "
    player, count = next(iter(occupants.items()))
    marker = "H" if player == "human" else "A"
    return f"{marker}{count}".ljust(3)


def _backgammon_move_summary(values: list[int]) -> str:
    return ", ".join(str(value) for value in values) if values else "none"


def _render_backgammon_board(state: dict[str, Any]) -> str:
    cells = [_backgammon_cell(occupants) for occupants in state["points"]]
    top_left = " ".join(cells[12:18]).rstrip()
    top_right = " ".join(cells[18:24]).rstrip()
    bottom_left = " ".join(reversed(cells[6:12])).rstrip()
    bottom_right = " ".join(reversed(cells[0:6])).rstrip()
    dice = _backgammon_move_summary(state.get("dice", []))
    remaining_moves = _backgammon_move_summary(state.get("remaining_moves", []))

    return (
        "Backgammon — Human moves 24→1, Agent moves 1→24\n"
        "+-------------------------------------------------------------+\n"
        "| 13  14  15  16  17  18 | BAR | 19  20  21  22  23  24 |\n"
        f"| {top_left} |     | {top_right} |\n"
        "|-------------------------+-----+-------------------------|\n"
        f"| {bottom_left} |     | {bottom_right} |\n"
        "| 12  11  10  09  08  07 | BAR | 06  05  04  03  02  01 |\n"
        "+-------------------------------------------------------------+\n"
        f"Bar: Human {state['bar']['human']}, Agent {state['bar']['agent']} | "
        f"Off: Human {state['off']['human']}, Agent {state['off']['agent']} | "
        f"Dice: {dice} | Moves left: {remaining_moves}"
    )


def _with_backgammon_view(state: dict[str, Any]) -> dict[str, Any]:
    state = dict(state)
    state["rendered_board"] = _render_backgammon_board(state)
    return state


def backgammon_save_game(state: dict[str, Any]) -> dict[str, Any]:
    state_to_write = dict(state)
    state_to_write.pop("rendered_board", None)
    _backgammon_path(state_to_write["game_id"]).write_text(
        json.dumps(state_to_write, indent=2, sort_keys=True), encoding="utf-8"
    )
    return _with_backgammon_view(state_to_write)


def backgammon_new_game(game_id: str = TABLE_BACKGAMMON) -> dict[str, Any]:
    """Create or reset a minimal playable backgammon game."""
    state = {
        "game_id": _normalize_game_id(game_id),
        "game": "backgammon",
        "players": {"human": {"direction": -1}, "agent": {"direction": 1}},
        "points": _backgammon_standard_points(),
        "bar": {"human": 0, "agent": 0},
        "off": {"human": 0, "agent": 0},
        "turn": "human",
        "status": "playing",
        "winner": None,
        "dice": [],
        "remaining_moves": [],
        "moves": [],
        "error": None,
    }
    return backgammon_save_game(state)


def backgammon_load_game(game_id: str = TABLE_BACKGAMMON) -> dict[str, Any]:
    """Load an existing backgammon game, creating a fresh one if missing."""
    path = _backgammon_path(game_id)
    if not path.exists():
        return backgammon_new_game(game_id=game_id)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("corrupt backgammon state at %s; starting over", path)
        return backgammon_new_game(game_id=game_id)
    return _with_backgammon_view(state)


def _validate_backgammon_player(state: dict[str, Any], player: str) -> str | None:
    player = (player or "").strip().lower()
    if player not in BACKGAMMON_PLAYERS:
        return "Player must be human or agent."
    if state["status"] != "playing":
        return (
            f"Backgammon game {state['game_id']} is already {state['status']}. "
            "Start a new game to play again."
        )
    if player != state["turn"]:
        return f"It is {state['turn']}'s turn, not {player}'s."
    return None


def _normalize_die(value: int | None) -> int:
    die = random.randint(1, 6) if value is None else int(value)
    if die < 1 or die > 6:
        raise ValueError("Dice values must be from 1 to 6.")
    return die


def backgammon_roll(
    game_id: str = TABLE_BACKGAMMON,
    player: str = "human",
    die1: int | None = None,
    die2: int | None = None,
) -> dict[str, Any]:
    """Roll dice for the current backgammon player.

    die1/die2 are optional test hooks; omit them for real random dice.
    """
    state = backgammon_load_game(game_id)
    state.pop("rendered_board", None)
    state["error"] = None
    player = (player or "").strip().lower()

    error = _validate_backgammon_player(state, player)
    if error:
        state["error"] = error
        return _with_backgammon_view(state)

    if state["remaining_moves"]:
        state["error"] = "Finish or end the current turn before rolling again."
        return _with_backgammon_view(state)

    try:
        first = _normalize_die(die1)
        second = _normalize_die(die2)
    except (TypeError, ValueError) as exc:
        state["error"] = str(exc)
        return _with_backgammon_view(state)

    state["dice"] = [first, second]
    state["remaining_moves"] = [first] * 4 if first == second else [first, second]
    state["moves"].append({"player": player, "roll": state["dice"]})
    return backgammon_save_game(state)


def _point_index(point: int) -> int:
    point_int = int(point)
    if point_int < 1 or point_int > 24:
        raise ValueError("Point must be a number from 1 to 24.")
    return point_int - 1


def _point_owner(point: dict[str, int]) -> str | None:
    if not point:
        return None
    return next(iter(point.keys()))


def _move_distance(player: str, from_idx: int, to_idx: int) -> int:
    return from_idx - to_idx if player == "human" else to_idx - from_idx


def _opponent(player: str) -> str:
    return "agent" if player == "human" else "human"


def backgammon_move(
    game_id: str = TABLE_BACKGAMMON,
    player: str = "human",
    from_point: int = 24,
    to_point: int = 23,
) -> dict[str, Any]:
    """Move one checker using one available die.

    Rule core: point-to-point moves, directional movement, blocked points,
    hitting blots, dice consumption, and win detection. Checkers on the bar
    must be entered with backgammon_enter before other moves; bearing off
    happens through backgammon_bear_off.
    """
    state = backgammon_load_game(game_id)
    state.pop("rendered_board", None)
    state["error"] = None
    player = (player or "").strip().lower()

    error = _validate_backgammon_player(state, player)
    if error:
        state["error"] = error
        return _with_backgammon_view(state)

    if not state["remaining_moves"]:
        state["error"] = "Roll before moving."
        return _with_backgammon_view(state)

    if state["bar"][player] > 0:
        state["error"] = (
            f"{player} has {state['bar'][player]} checker(s) on the bar and must enter "
            "them first with backgammon_enter."
        )
        return _with_backgammon_view(state)

    try:
        from_idx = _point_index(from_point)
        to_idx = _point_index(to_point)
    except (TypeError, ValueError) as exc:
        state["error"] = str(exc)
        return _with_backgammon_view(state)

    source = state["points"][from_idx]
    if source.get(player, 0) <= 0:
        state["error"] = f"Point {int(from_point)} has no {player} checker to move."
        return _with_backgammon_view(state)

    distance = _move_distance(player, from_idx, to_idx)
    if distance <= 0:
        state["error"] = f"{player} must move {'toward lower' if player == 'human' else 'toward higher'} points."
        return _with_backgammon_view(state)

    if distance not in state["remaining_moves"]:
        state["error"] = f"Move distance {distance} is not available in remaining dice {state['remaining_moves']}."
        return _with_backgammon_view(state)

    target = state["points"][to_idx]
    target_owner = _point_owner(target)
    opponent = _opponent(player)
    if target_owner == opponent and target.get(opponent, 0) > 1:
        state["error"] = f"Point {int(to_point)} is blocked by {opponent}."
        return _with_backgammon_view(state)

    source[player] -= 1
    if source[player] == 0:
        source.pop(player)

    hit = False
    if target_owner == opponent and target.get(opponent, 0) == 1:
        target.pop(opponent)
        state["bar"][opponent] += 1
        hit = True

    target[player] = target.get(player, 0) + 1
    state["remaining_moves"].remove(distance)
    state["moves"].append(
        {
            "player": player,
            "from_point": int(from_point),
            "to_point": int(to_point),
            "die": distance,
            "hit": hit,
        }
    )

    return _backgammon_finish_move(state, player)


def _backgammon_entry_distance(player: str, to_idx: int) -> int:
    """Die value needed to enter from the bar onto to_idx (0-23)."""
    return 24 - to_idx if player == "human" else to_idx + 1


def _backgammon_home_indices(player: str) -> range:
    """Board indices of the player's home board (where bearing off happens)."""
    return range(0, 6) if player == "human" else range(18, 24)


def _backgammon_all_home(state: dict[str, Any], player: str) -> bool:
    if state["bar"][player] > 0:
        return False
    home = set(_backgammon_home_indices(player))
    return all(
        idx in home
        for idx, occupants in enumerate(state["points"])
        if occupants.get(player, 0) > 0
    )


def _backgammon_finish_move(state: dict[str, Any], player: str) -> dict[str, Any]:
    """Shared end-of-move bookkeeping: win detection and turn hand-off."""
    if state["off"][player] >= 15:
        state["status"] = "won"
        state["winner"] = player
        state["remaining_moves"] = []
        state["dice"] = []
        opponent_off = state["off"][_opponent(player)]
        _record_result(
            state,
            "a gammon — the opponent bore off nothing" if opponent_off == 0 else f"bore off all fifteen to the opponent's {opponent_off}",
        )
    elif not state["remaining_moves"]:
        state["turn"] = _opponent(player)
        state["dice"] = []
    return backgammon_save_game(state)


def backgammon_enter(
    game_id: str = TABLE_BACKGAMMON,
    player: str = "human",
    to_point: int = 24,
) -> dict[str, Any]:
    """Enter one checker from the bar using an available die.

    Human enters on points 24-19 (die 1-6), Agent enters on points 1-6 (die 1-6).
    """
    state = backgammon_load_game(game_id)
    state.pop("rendered_board", None)
    state["error"] = None
    player = (player or "").strip().lower()

    error = _validate_backgammon_player(state, player)
    if error:
        state["error"] = error
        return _with_backgammon_view(state)

    if not state["remaining_moves"]:
        state["error"] = "Roll before entering from the bar."
        return _with_backgammon_view(state)

    if state["bar"][player] <= 0:
        state["error"] = f"{player} has no checkers on the bar."
        return _with_backgammon_view(state)

    try:
        to_idx = _point_index(to_point)
    except (TypeError, ValueError) as exc:
        state["error"] = str(exc)
        return _with_backgammon_view(state)

    entry_points = "24-19" if player == "human" else "1-6"
    distance = _backgammon_entry_distance(player, to_idx)
    if distance < 1 or distance > 6:
        state["error"] = f"{player} can only enter on points {entry_points}."
        return _with_backgammon_view(state)

    if distance not in state["remaining_moves"]:
        state["error"] = (
            f"Entering on point {int(to_point)} needs a {distance}, "
            f"which is not in remaining dice {state['remaining_moves']}."
        )
        return _with_backgammon_view(state)

    target = state["points"][to_idx]
    opponent = _opponent(player)
    if target.get(opponent, 0) > 1:
        state["error"] = f"Point {int(to_point)} is blocked by {opponent}."
        return _with_backgammon_view(state)

    hit = False
    if target.get(opponent, 0) == 1:
        target.pop(opponent)
        state["bar"][opponent] += 1
        hit = True

    state["bar"][player] -= 1
    target[player] = target.get(player, 0) + 1
    state["remaining_moves"].remove(distance)
    state["moves"].append(
        {"player": player, "enter_point": int(to_point), "die": distance, "hit": hit}
    )
    return _backgammon_finish_move(state, player)


def backgammon_bear_off(
    game_id: str = TABLE_BACKGAMMON,
    player: str = "human",
    from_point: int = 1,
) -> dict[str, Any]:
    """Bear one checker off the board.

    Allowed only once every checker is in the player's home board (Human: points
    1-6, Agent: points 19-24). An exact die is used when available; a larger die
    may be used only when no checker sits farther from the edge.
    """
    state = backgammon_load_game(game_id)
    state.pop("rendered_board", None)
    state["error"] = None
    player = (player or "").strip().lower()

    error = _validate_backgammon_player(state, player)
    if error:
        state["error"] = error
        return _with_backgammon_view(state)

    if not state["remaining_moves"]:
        state["error"] = "Roll before bearing off."
        return _with_backgammon_view(state)

    if not _backgammon_all_home(state, player):
        home_points = "1-6" if player == "human" else "19-24"
        state["error"] = (
            f"{player} may only bear off once every checker is home on points {home_points}."
        )
        return _with_backgammon_view(state)

    try:
        from_idx = _point_index(from_point)
    except (TypeError, ValueError) as exc:
        state["error"] = str(exc)
        return _with_backgammon_view(state)

    if state["points"][from_idx].get(player, 0) <= 0:
        state["error"] = f"Point {int(from_point)} has no {player} checker to bear off."
        return _with_backgammon_view(state)

    distance = from_idx + 1 if player == "human" else 24 - from_idx
    if distance in state["remaining_moves"]:
        die = distance
    else:
        larger = sorted(value for value in state["remaining_moves"] if value > distance)
        farther = [
            idx
            for idx in _backgammon_home_indices(player)
            if state["points"][idx].get(player, 0) > 0
            and (idx > from_idx if player == "human" else idx < from_idx)
        ]
        if not larger or farther:
            state["error"] = (
                f"Bearing off from point {int(from_point)} needs a {distance} "
                f"(or a larger die with no checker farther back); remaining dice {state['remaining_moves']}."
            )
            return _with_backgammon_view(state)
        die = larger[0]

    source = state["points"][from_idx]
    source[player] -= 1
    if source[player] == 0:
        source.pop(player)
    state["off"][player] += 1
    state["remaining_moves"].remove(die)
    state["moves"].append(
        {"player": player, "bear_off_point": int(from_point), "die": die}
    )
    return _backgammon_finish_move(state, player)


def backgammon_end_turn(game_id: str = TABLE_BACKGAMMON, player: str = "human") -> dict[str, Any]:
    """End the current backgammon turn, discarding unused dice."""
    state = backgammon_load_game(game_id)
    state.pop("rendered_board", None)
    state["error"] = None
    player = (player or "").strip().lower()

    error = _validate_backgammon_player(state, player)
    if error:
        state["error"] = error
        return _with_backgammon_view(state)

    state["remaining_moves"] = []
    state["dice"] = []
    state["turn"] = _opponent(player)
    state["moves"].append({"player": player, "end_turn": True})
    return backgammon_save_game(state)


CONNECT4_ROWS = 6
CONNECT4_COLS = 7


def _connect4_path(game_id: str) -> Path:
    return _games_dir() / f"{_normalize_game_id(game_id)}.connect4.json"


def _render_connect4_board(state: dict[str, Any]) -> str:
    symbols = {"human": "R", "agent": "J", "": "·"}
    rows = []
    for row in range(CONNECT4_ROWS):
        cells = [
            symbols[state["board"][row * CONNECT4_COLS + col]]
            for col in range(CONNECT4_COLS)
        ]
        rows.append(" ".join(cells))
    header = " ".join(str(col + 1) for col in range(CONNECT4_COLS))
    return "Connect Four — drop into a column 1-7\n" + header + "\n" + "\n".join(rows)


def _with_connect4_view(state: dict[str, Any]) -> dict[str, Any]:
    state = dict(state)
    state["rendered_board"] = _render_connect4_board(state)
    return state


def connect4_save_game(state: dict[str, Any]) -> dict[str, Any]:
    state_to_write = dict(state)
    state_to_write.pop("rendered_board", None)
    _connect4_path(state_to_write["game_id"]).write_text(
        json.dumps(state_to_write, indent=2, sort_keys=True), encoding="utf-8"
    )
    return _with_connect4_view(state_to_write)


def connect4_new_game(game_id: str = TABLE_CONNECT4) -> dict[str, Any]:
    """Create or reset a Connect Four game."""
    state = {
        "game_id": _normalize_game_id(game_id),
        "game": "connect-four",
        "board": [EMPTY] * (CONNECT4_ROWS * CONNECT4_COLS),
        "turn": "human",
        "status": "playing",
        "winner": None,
        "winning_cells": None,
        "moves": [],
        "error": None,
    }
    return connect4_save_game(state)


def connect4_load_game(game_id: str = TABLE_CONNECT4) -> dict[str, Any]:
    """Load an existing Connect Four game, creating a fresh one if missing."""
    path = _connect4_path(game_id)
    if not path.exists():
        return connect4_new_game(game_id=game_id)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("corrupt Connect Four state at %s; starting over", path)
        return connect4_new_game(game_id=game_id)
    return _with_connect4_view(state)


def _connect4_evaluate(state: dict[str, Any]) -> None:
    board = state["board"]

    def cell(row: int, col: int) -> str:
        return board[row * CONNECT4_COLS + col]

    for row in range(CONNECT4_ROWS):
        for col in range(CONNECT4_COLS):
            player = cell(row, col)
            if not player:
                continue
            for d_row, d_col in ((0, 1), (1, 0), (1, 1), (1, -1)):
                end_row = row + 3 * d_row
                end_col = col + 3 * d_col
                if not (0 <= end_row < CONNECT4_ROWS and 0 <= end_col < CONNECT4_COLS):
                    continue
                cells = [(row + i * d_row, col + i * d_col) for i in range(4)]
                if all(cell(r, c) == player for r, c in cells):
                    state["status"] = "won"
                    state["winner"] = player
                    state["winning_cells"] = [r * CONNECT4_COLS + c + 1 for r, c in cells]
                    return
    if all(board):
        state["status"] = "draw"
        state["winner"] = None
        state["winning_cells"] = None


def connect4_drop(game_id: str = TABLE_CONNECT4, player: str = "human", column: int = 1) -> dict[str, Any]:
    """Drop a checker into a column for Human or Agent.

    Args:
        game_id: Which table to play at; the default is the room's.
        player: human or agent.
        column: Column 1-7, left to right.
    """
    state = connect4_load_game(game_id)
    state.pop("rendered_board", None)
    state["error"] = None

    player = (player or "").strip().lower()
    if player not in PLAYERS:
        state["error"] = "Player must be human or agent."
        return _with_connect4_view(state)

    if state["status"] != "playing":
        state["error"] = (
            f"Game {state['game_id']} is already {state['status']}. "
            "Start a new game to play again."
        )
        return _with_connect4_view(state)

    if player != state["turn"]:
        state["error"] = f"It is {state['turn']}'s turn, not {player}'s."
        return _with_connect4_view(state)

    try:
        col = int(column)
    except (TypeError, ValueError):
        state["error"] = "Column must be a number from 1 to 7."
        return _with_connect4_view(state)

    if col < 1 or col > CONNECT4_COLS:
        state["error"] = "Column must be a number from 1 to 7."
        return _with_connect4_view(state)

    col_idx = col - 1
    landed_row = None
    for row in range(CONNECT4_ROWS - 1, -1, -1):
        if not state["board"][row * CONNECT4_COLS + col_idx]:
            landed_row = row
            break
    if landed_row is None:
        state["error"] = f"Column {col} is full."
        return _with_connect4_view(state)

    state["board"][landed_row * CONNECT4_COLS + col_idx] = player
    state["moves"].append({"player": player, "column": col, "row": landed_row + 1})
    state["turn"] = "agent" if player == "human" else "human"
    _connect4_evaluate(state)
    if state["status"] == "won":
        cells = state["winning_cells"] or []
        columns = sorted({(cell - 1) % CONNECT4_COLS + 1 for cell in cells})
        _record_result(state, f"four in a row through columns {columns}")
    elif state["status"] == "draw":
        _record_result(state, "the grid filled with no line of four")
    return connect4_save_game(state)


CHECKERS_SIZE = 8
CHECKERS_DIRECTIONS = {
    "human": ((-1, -1), (-1, 1)),
    "agent": ((1, -1), (1, 1)),
}
CHECKERS_KING_DIRECTIONS = ((-1, -1), (-1, 1), (1, -1), (1, 1))


def _checkers_path(game_id: str) -> Path:
    return _games_dir() / f"{_normalize_game_id(game_id)}.checkers.json"


def _checkers_owner(piece: str) -> str | None:
    if piece.startswith("human"):
        return "human"
    if piece.startswith("agent"):
        return "agent"
    return None


def _checkers_is_king(piece: str) -> bool:
    return piece.endswith("-king")


def _checkers_dark(row: int, col: int) -> bool:
    return (row + col) % 2 == 1


def _checkers_start_board() -> list[str]:
    board = [EMPTY] * (CHECKERS_SIZE * CHECKERS_SIZE)
    for row in range(CHECKERS_SIZE):
        for col in range(CHECKERS_SIZE):
            if not _checkers_dark(row, col):
                continue
            if row < 3:
                board[row * CHECKERS_SIZE + col] = "agent"
            elif row > 4:
                board[row * CHECKERS_SIZE + col] = "human"
    return board


def _render_checkers_board(state: dict[str, Any]) -> str:
    symbols = {"human": "r", "human-king": "R", "agent": "j", "agent-king": "J", "": "·"}
    rows = []
    for row in range(CHECKERS_SIZE):
        first_square = row * CHECKERS_SIZE + 1
        cells = " ".join(
            symbols[state["board"][row * CHECKERS_SIZE + col]]
            for col in range(CHECKERS_SIZE)
        )
        rows.append(f"{first_square:>2}  {cells}")
    return (
        "Checkers — squares numbered 1-64, left to right from the top row.\n"
        "Human (r/R) moves up toward row 1; Agent (j/J) moves down toward row 8.\n"
        "Row starts at square:\n" + "\n".join(rows)
    )


def _with_checkers_view(state: dict[str, Any]) -> dict[str, Any]:
    state = dict(state)
    state["rendered_board"] = _render_checkers_board(state)
    return state


def checkers_save_game(state: dict[str, Any]) -> dict[str, Any]:
    state_to_write = dict(state)
    state_to_write.pop("rendered_board", None)
    _checkers_path(state_to_write["game_id"]).write_text(
        json.dumps(state_to_write, indent=2, sort_keys=True), encoding="utf-8"
    )
    return _with_checkers_view(state_to_write)


def checkers_new_game(game_id: str = TABLE_CHECKERS) -> dict[str, Any]:
    """Create or reset a checkers game."""
    state = {
        "game_id": _normalize_game_id(game_id),
        "game": "checkers",
        "board": _checkers_start_board(),
        "turn": "human",
        "status": "playing",
        "winner": None,
        "must_continue_from": None,
        "moves": [],
        "error": None,
    }
    return checkers_save_game(state)


def checkers_load_game(game_id: str = TABLE_CHECKERS) -> dict[str, Any]:
    """Load an existing checkers game, creating a fresh one if missing."""
    path = _checkers_path(game_id)
    if not path.exists():
        return checkers_new_game(game_id=game_id)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("corrupt checkers state at %s; starting over", path)
        return checkers_new_game(game_id=game_id)
    return _with_checkers_view(state)


def _checkers_piece_directions(piece: str) -> tuple[tuple[int, int], ...]:
    if _checkers_is_king(piece):
        return CHECKERS_KING_DIRECTIONS
    return CHECKERS_DIRECTIONS[_checkers_owner(piece)]


def _checkers_captures_from(board: list[str], idx: int) -> list[tuple[int, int]]:
    """Return (landing_idx, captured_idx) jumps available to the piece at idx."""
    piece = board[idx]
    row, col = divmod(idx, CHECKERS_SIZE)
    player = _checkers_owner(piece)
    jumps = []
    for d_row, d_col in _checkers_piece_directions(piece):
        mid_row, mid_col = row + d_row, col + d_col
        land_row, land_col = row + 2 * d_row, col + 2 * d_col
        if not (0 <= land_row < CHECKERS_SIZE and 0 <= land_col < CHECKERS_SIZE):
            continue
        mid_idx = mid_row * CHECKERS_SIZE + mid_col
        land_idx = land_row * CHECKERS_SIZE + land_col
        if _checkers_owner(board[mid_idx]) == _opponent(player) and not board[land_idx]:
            jumps.append((land_idx, mid_idx))
    return jumps


def _checkers_simple_moves_from(board: list[str], idx: int) -> list[int]:
    piece = board[idx]
    row, col = divmod(idx, CHECKERS_SIZE)
    targets = []
    for d_row, d_col in _checkers_piece_directions(piece):
        to_row, to_col = row + d_row, col + d_col
        if not (0 <= to_row < CHECKERS_SIZE and 0 <= to_col < CHECKERS_SIZE):
            continue
        to_idx = to_row * CHECKERS_SIZE + to_col
        if not board[to_idx]:
            targets.append(to_idx)
    return targets


def _checkers_player_squares(board: list[str], player: str) -> list[int]:
    return [idx for idx, piece in enumerate(board) if _checkers_owner(piece) == player]


def _checkers_player_has_capture(board: list[str], player: str) -> bool:
    return any(
        _checkers_captures_from(board, idx)
        for idx in _checkers_player_squares(board, player)
    )


def _checkers_player_has_move(board: list[str], player: str) -> bool:
    return any(
        _checkers_captures_from(board, idx) or _checkers_simple_moves_from(board, idx)
        for idx in _checkers_player_squares(board, player)
    )


def checkers_move(
    game_id: str = TABLE_CHECKERS,
    player: str = "human",
    from_square: int = 1,
    to_square: int = 1,
) -> dict[str, Any]:
    """Move a checkers piece for Human or Agent.

    Squares are numbered 1-64, left to right from the top row. Captures are
    mandatory; after a jump the same piece must keep jumping while it can
    (the game reports must_continue_from). Reaching the far row crowns a king
    and ends the turn.
    """
    state = checkers_load_game(game_id)
    state.pop("rendered_board", None)
    state["error"] = None

    player = (player or "").strip().lower()
    if player not in PLAYERS:
        state["error"] = "Player must be human or agent."
        return _with_checkers_view(state)

    if state["status"] != "playing":
        state["error"] = (
            f"Game {state['game_id']} is already {state['status']}. "
            "Start a new game to play again."
        )
        return _with_checkers_view(state)

    if player != state["turn"]:
        state["error"] = f"It is {state['turn']}'s turn, not {player}'s."
        return _with_checkers_view(state)

    try:
        from_idx = int(from_square) - 1
        to_idx = int(to_square) - 1
    except (TypeError, ValueError):
        state["error"] = "Squares must be numbers from 1 to 64."
        return _with_checkers_view(state)

    if not (0 <= from_idx < 64 and 0 <= to_idx < 64):
        state["error"] = "Squares must be numbers from 1 to 64."
        return _with_checkers_view(state)

    board = state["board"]
    if _checkers_owner(board[from_idx]) != player:
        state["error"] = f"Square {from_idx + 1} has no {player} piece to move."
        return _with_checkers_view(state)

    if state["must_continue_from"] is not None and from_idx != state["must_continue_from"] - 1:
        state["error"] = (
            f"The piece on square {state['must_continue_from']} is mid-jump and must "
            "continue capturing."
        )
        return _with_checkers_view(state)

    captures = _checkers_captures_from(board, from_idx)
    capture_targets = {land: mid for land, mid in captures}

    if to_idx in capture_targets:
        captured_idx = capture_targets[to_idx]
    else:
        if state["must_continue_from"] is not None:
            state["error"] = "That piece must keep jumping while a capture is available."
            return _with_checkers_view(state)
        if _checkers_player_has_capture(board, player):
            state["error"] = "A capture is available; you must jump."
            return _with_checkers_view(state)
        if to_idx not in _checkers_simple_moves_from(board, from_idx):
            state["error"] = (
                f"Square {from_idx + 1} cannot move to square {to_idx + 1}."
            )
            return _with_checkers_view(state)
        captured_idx = None

    piece = board[from_idx]
    board[from_idx] = EMPTY
    if captured_idx is not None:
        board[captured_idx] = EMPTY

    to_row = to_idx // CHECKERS_SIZE
    crowned = False
    if not _checkers_is_king(piece):
        if (player == "human" and to_row == 0) or (player == "agent" and to_row == CHECKERS_SIZE - 1):
            piece = f"{player}-king"
            crowned = True
    board[to_idx] = piece

    state["moves"].append(
        {
            "player": player,
            "from_square": from_idx + 1,
            "to_square": to_idx + 1,
            "captured_square": captured_idx + 1 if captured_idx is not None else None,
            "crowned": crowned,
        }
    )

    opponent = _opponent(player)
    continues = (
        captured_idx is not None
        and not crowned
        and _checkers_captures_from(board, to_idx)
    )
    if continues:
        state["must_continue_from"] = to_idx + 1
    else:
        state["must_continue_from"] = None
        state["turn"] = opponent
        if not _checkers_player_has_move(board, opponent):
            state["status"] = "won"
            state["winner"] = player
            pieces_left = len(_checkers_player_squares(board, opponent))
            _record_result(
                state,
                "opponent had no pieces left" if pieces_left == 0 else "opponent had no legal move",
            )

    return checkers_save_game(state)


# ── Chess ────────────────────────────────────────────────────────────────────
# Human plays White (ember pieces), Agent plays Black (cream pieces).
CHESS_FILES = "abcdefgh"
CHESS_COLORS = {"human": "w", "agent": "b"}
CHESS_KNIGHT_STEPS = ((-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1))
CHESS_DIAGONALS = ((-1, -1), (-1, 1), (1, -1), (1, 1))
CHESS_ORTHOGONALS = ((-1, 0), (1, 0), (0, -1), (0, 1))
CHESS_UNICODE = {
    "wK": "♔", "wQ": "♕", "wR": "♖", "wB": "♗", "wN": "♘", "wP": "♙",
    "bK": "♚", "bQ": "♛", "bR": "♜", "bB": "♝", "bN": "♞", "bP": "♟",
}


def _chess_path(game_id: str) -> Path:
    return _games_dir() / f"{_normalize_game_id(game_id)}.chess.json"


def _chess_square_name(idx: int) -> str:
    row, col = divmod(idx, 8)
    return f"{CHESS_FILES[col]}{8 - row}"


def _chess_square_idx(name: str) -> int:
    name = (name or "").strip().lower()
    if len(name) != 2 or name[0] not in CHESS_FILES or name[1] not in "12345678":
        raise ValueError(f"Square {name!r} must look like e2.")
    return (8 - int(name[1])) * 8 + CHESS_FILES.index(name[0])


def _chess_start_board() -> list[str]:
    back = ["R", "N", "B", "Q", "K", "B", "N", "R"]
    board = [""] * 64
    for col in range(8):
        board[col] = f"b{back[col]}"
        board[8 + col] = "bP"
        board[48 + col] = "wP"
        board[56 + col] = f"w{back[col]}"
    return board


def _chess_color(piece: str) -> str | None:
    return piece[0] if piece else None


def _chess_pseudo_targets(
    board: list[str], idx: int, ep_target: int | None, attacks_only: bool = False
) -> list[int]:
    """Pseudo-legal targets for the piece at idx (no self-check filtering)."""
    piece = board[idx]
    color, kind = piece[0], piece[1]
    row, col = divmod(idx, 8)
    out: list[int] = []

    def on_board(r: int, c: int) -> bool:
        return 0 <= r < 8 and 0 <= c < 8

    if kind == "P":
        step = -1 if color == "w" else 1
        for dc in (-1, 1):
            r, c = row + step, col + dc
            if not on_board(r, c):
                continue
            target = r * 8 + c
            if attacks_only:
                out.append(target)
            elif board[target] and board[target][0] != color:
                out.append(target)
            elif ep_target is not None and target == ep_target:
                out.append(target)
        if not attacks_only:
            r = row + step
            if on_board(r, col) and not board[r * 8 + col]:
                out.append(r * 8 + col)
                start_row = 6 if color == "w" else 1
                r2 = row + 2 * step
                if row == start_row and not board[r2 * 8 + col]:
                    out.append(r2 * 8 + col)
        return out

    if kind == "N":
        steps = CHESS_KNIGHT_STEPS
    elif kind == "K":
        steps = CHESS_DIAGONALS + CHESS_ORTHOGONALS
    else:
        rays = {
            "B": CHESS_DIAGONALS,
            "R": CHESS_ORTHOGONALS,
            "Q": CHESS_DIAGONALS + CHESS_ORTHOGONALS,
        }[kind]
        for d_row, d_col in rays:
            r, c = row + d_row, col + d_col
            while on_board(r, c):
                target = r * 8 + c
                if board[target]:
                    if attacks_only or board[target][0] != color:
                        out.append(target)
                    break
                out.append(target)
                r += d_row
                c += d_col
        return out

    for d_row, d_col in steps:
        r, c = row + d_row, col + d_col
        if not on_board(r, c):
            continue
        target = r * 8 + c
        if attacks_only or not board[target] or board[target][0] != color:
            out.append(target)
    return out


def _chess_attacked(board: list[str], square: int, by_color: str) -> bool:
    for idx, piece in enumerate(board):
        if piece and piece[0] == by_color:
            if square in _chess_pseudo_targets(board, idx, None, attacks_only=True):
                return True
    return False


def _chess_king_square(board: list[str], color: str) -> int:
    return board.index(f"{color}K")


def _chess_apply(board: list[str], from_idx: int, to_idx: int, ep_target: int | None,
                 promotion: str = "q") -> tuple[list[str], bool, bool]:
    """Return (new board, was_capture, was_pawn_move) after one move."""
    board = list(board)
    piece = board[from_idx]
    color, kind = piece[0], piece[1]
    capture = bool(board[to_idx])
    if kind == "P" and ep_target is not None and to_idx == ep_target and not board[to_idx]:
        behind = to_idx + (8 if color == "w" else -8)
        board[behind] = ""
        capture = True
    board[from_idx] = ""
    if kind == "P" and (to_idx // 8 == 0 or to_idx // 8 == 7):
        board[to_idx] = f"{color}{(promotion or 'q').strip().upper()[:1] or 'Q'}"
    else:
        board[to_idx] = piece
    if kind == "K" and abs(to_idx - from_idx) == 2:
        row_base = from_idx - from_idx % 8
        if to_idx > from_idx:  # kingside: rook h-file to f-file
            board[row_base + 5] = board[row_base + 7]
            board[row_base + 7] = ""
        else:  # queenside: rook a-file to d-file
            board[row_base + 3] = board[row_base + 0]
            board[row_base + 0] = ""
    return board, capture, kind == "P"


def _chess_castle_targets(state: dict[str, Any], color: str) -> list[int]:
    board = state["board"]
    enemy = "b" if color == "w" else "w"
    rights = state["castling"]["human" if color == "w" else "agent"]
    row_base = 56 if color == "w" else 0
    king_idx = row_base + 4
    if board[king_idx] != f"{color}K" or _chess_attacked(board, king_idx, enemy):
        return []
    out = []
    if (
        rights.get("kingside")
        and board[row_base + 7] == f"{color}R"
        and not board[row_base + 5] and not board[row_base + 6]
        and not _chess_attacked(board, row_base + 5, enemy)
        and not _chess_attacked(board, row_base + 6, enemy)
    ):
        out.append(row_base + 6)
    if (
        rights.get("queenside")
        and board[row_base + 0] == f"{color}R"
        and not board[row_base + 1] and not board[row_base + 2] and not board[row_base + 3]
        and not _chess_attacked(board, row_base + 3, enemy)
        and not _chess_attacked(board, row_base + 2, enemy)
    ):
        out.append(row_base + 2)
    return out


def _chess_legal_moves(state: dict[str, Any], player: str) -> dict[int, list[int]]:
    board = state["board"]
    color = CHESS_COLORS[player]
    enemy = "b" if color == "w" else "w"
    ep_name = state.get("en_passant")
    ep_target = _chess_square_idx(ep_name) if ep_name else None
    moves: dict[int, list[int]] = {}
    for idx, piece in enumerate(board):
        if not piece or piece[0] != color:
            continue
        targets = list(_chess_pseudo_targets(board, idx, ep_target))
        if piece[1] == "K":
            targets += _chess_castle_targets(state, color)
        legal = []
        for target in targets:
            candidate, _, _ = _chess_apply(board, idx, target, ep_target)
            if not _chess_attacked(candidate, _chess_king_square(candidate, color), enemy):
                legal.append(target)
        if legal:
            moves[idx] = sorted(legal)
    return moves


def _chess_position_key(state: dict[str, Any]) -> str:
    rights = state["castling"]
    return "|".join([
        "".join(piece or "." for piece in state["board"]),
        state["turn"],
        json.dumps(rights, sort_keys=True),
        state.get("en_passant") or "-",
    ])


def _chess_insufficient_material(board: list[str]) -> bool:
    minor_squares: list[tuple[str, int]] = []
    for idx, piece in enumerate(board):
        if not piece or piece[1] == "K":
            continue
        if piece[1] in ("Q", "R", "P"):
            return False
        minor_squares.append((piece[1], idx))
    if len(minor_squares) <= 1:
        return True
    if len(minor_squares) == 2 and all(kind == "B" for kind, _ in minor_squares):
        shades = {(idx // 8 + idx % 8) % 2 for _, idx in minor_squares}
        return len(shades) == 1
    return False


def _render_chess_board(state: dict[str, Any]) -> str:
    rows = []
    for row in range(8):
        rank = 8 - row
        cells = " ".join(
            CHESS_UNICODE.get(state["board"][row * 8 + col], "·") for col in range(8)
        )
        rows.append(f"{rank}  {cells}")
    rows.append("   a b c d e f g h")
    header = "Chess — Human is White (♔), moving up. Agent is Black (♚)."
    extras = []
    if state.get("in_check"):
        extras.append(f"{state['turn']} is in check")
    if state.get("status") == "won":
        extras.append(f"checkmate — {state['winner']} wins")
    elif state.get("status") == "draw":
        extras.append(f"draw: {state.get('draw_reason') or 'agreed'}")
    footer = (" | ".join(extras)) if extras else f"{state.get('turn')}'s move"
    return header + "\n" + "\n".join(rows) + "\n" + footer


def _with_chess_view(state: dict[str, Any]) -> dict[str, Any]:
    state = dict(state)
    state["rendered_board"] = _render_chess_board(state)
    if state.get("status") == "playing":
        legal = _chess_legal_moves(state, state["turn"])
        state["legal_moves"] = {
            _chess_square_name(source): [_chess_square_name(t) for t in targets]
            for source, targets in legal.items()
        }
    else:
        state["legal_moves"] = {}
    return state


def chess_save_game(state: dict[str, Any]) -> dict[str, Any]:
    state_to_write = dict(state)
    state_to_write.pop("rendered_board", None)
    state_to_write.pop("legal_moves", None)
    _chess_path(state_to_write["game_id"]).write_text(
        json.dumps(state_to_write, indent=2, sort_keys=True), encoding="utf-8"
    )
    return _with_chess_view(state_to_write)


def chess_new_game(game_id: str = TABLE_CHESS) -> dict[str, Any]:
    """Create or reset a chess game. Human is White and moves first."""
    state = {
        "game_id": _normalize_game_id(game_id),
        "game": "chess",
        "board": _chess_start_board(),
        "turn": "human",
        "status": "playing",
        "winner": None,
        "in_check": False,
        "draw_reason": None,
        "castling": {
            "human": {"kingside": True, "queenside": True},
            "agent": {"kingside": True, "queenside": True},
        },
        "en_passant": None,
        "halfmove_clock": 0,
        "position_counts": {},
        "moves": [],
        "error": None,
    }
    state["position_counts"] = {_chess_position_key(state): 1}
    return chess_save_game(state)


def chess_load_game(game_id: str = TABLE_CHESS) -> dict[str, Any]:
    """Load an existing chess game, creating a fresh one if missing."""
    path = _chess_path(game_id)
    if not path.exists():
        return chess_new_game(game_id=game_id)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("corrupt chess state at %s; starting over", path)
        return chess_new_game(game_id=game_id)
    return _with_chess_view(state)


def chess_submit_move(
    game_id: str = TABLE_CHESS,
    player: str = "human",
    from_square: str = "e2",
    to_square: str = "e4",
    promotion: str = "q",
) -> dict[str, Any]:
    """Play one chess move using algebraic squares like e2 → e4.

    Castle by moving the king two squares (e1→g1 or e1→c1). Pawns reaching the
    last rank promote to `promotion` (q, r, b, or n; queen by default).
    """
    state = chess_load_game(game_id)
    state.pop("rendered_board", None)
    state.pop("legal_moves", None)
    state["error"] = None

    player = (player or "").strip().lower()
    if player not in PLAYERS:
        state["error"] = "Player must be human or agent."
        return _with_chess_view(state)
    if state["status"] != "playing":
        state["error"] = (
            f"Game {state['game_id']} is already {state['status']}. "
            "Start a new game to play again."
        )
        return _with_chess_view(state)
    if player != state["turn"]:
        state["error"] = f"It is {state['turn']}'s turn, not {player}'s."
        return _with_chess_view(state)

    promotion = (promotion or "q").strip().lower()
    if promotion not in ("q", "r", "b", "n"):
        state["error"] = "Promotion must be q, r, b, or n."
        return _with_chess_view(state)

    try:
        from_idx = _chess_square_idx(from_square)
        to_idx = _chess_square_idx(to_square)
    except ValueError as exc:
        state["error"] = str(exc)
        return _with_chess_view(state)

    color = CHESS_COLORS[player]
    piece = state["board"][from_idx]
    if not piece or piece[0] != color:
        state["error"] = f"Square {_chess_square_name(from_idx)} has no {player} piece."
        return _with_chess_view(state)

    legal = _chess_legal_moves(state, player)
    if to_idx not in legal.get(from_idx, []):
        state["error"] = (
            f"{_chess_square_name(from_idx)} → {_chess_square_name(to_idx)} is not a legal move."
        )
        return _with_chess_view(state)

    ep_name = state.get("en_passant")
    ep_target = _chess_square_idx(ep_name) if ep_name else None
    board, capture, pawn_move = _chess_apply(
        state["board"], from_idx, to_idx, ep_target, promotion
    )
    state["board"] = board

    # Castling rights fade when kings or rooks move, or a rook is captured.
    rights = state["castling"]
    for side, row_base in (("human", 56), ("agent", 0)):
        side_color = CHESS_COLORS[side]
        if board[row_base + 4] != f"{side_color}K":
            rights[side] = {"kingside": False, "queenside": False}
        else:
            if board[row_base + 7] != f"{side_color}R":
                rights[side]["kingside"] = False
            if board[row_base + 0] != f"{side_color}R":
                rights[side]["queenside"] = False

    if piece[1] == "P" and abs(to_idx - from_idx) == 16:
        state["en_passant"] = _chess_square_name((from_idx + to_idx) // 2)
    else:
        state["en_passant"] = None

    state["halfmove_clock"] = 0 if (capture or pawn_move) else state["halfmove_clock"] + 1
    promoted = piece[1] == "P" and (to_idx // 8 in (0, 7))
    state["moves"].append({
        "player": player,
        "from": _chess_square_name(from_idx),
        "to": _chess_square_name(to_idx),
        "piece": piece,
        "capture": capture,
        "promotion": promotion if promoted else None,
    })

    opponent = _opponent(player)
    state["turn"] = opponent
    enemy_color = CHESS_COLORS[opponent]
    in_check = _chess_attacked(
        board, _chess_king_square(board, enemy_color), color
    )
    state["in_check"] = in_check

    key = _chess_position_key(state)
    state["position_counts"][key] = state["position_counts"].get(key, 0) + 1

    if not _chess_legal_moves(state, opponent):
        if in_check:
            state["status"] = "won"
            state["winner"] = player
            _record_result(state, f"checkmate on move {len(state['moves'])}")
        else:
            state["status"] = "draw"
            state["draw_reason"] = "stalemate"
            _record_result(state, "stalemate — no legal move, no check")
    elif state["halfmove_clock"] >= 100:
        state["status"] = "draw"
        state["draw_reason"] = "fifty-move rule"
        _record_result(state, "fifty moves without a capture or pawn move")
    elif state["position_counts"][key] >= 3:
        state["status"] = "draw"
        state["draw_reason"] = "threefold repetition"
        _record_result(state, "the same position arose three times")
    elif _chess_insufficient_material(board):
        state["status"] = "draw"
        state["draw_reason"] = "insufficient material"
        _record_result(state, "neither side had enough pieces to mate")

    return chess_save_game(state)


# ── Battleship ───────────────────────────────────────────────────────────────
# Two hidden 10×10 fleets. The saved file holds both, but every view — for the
# browser AND for the MCP tools — is redacted to one player's own fleet plus
# only the hit/miss/sunk results of their shots. Un-hit ships never leave here.
BATTLESHIP_SIZE = 10
BATTLESHIP_FLEET = (
    ("Carrier", 5),
    ("Battleship", 4),
    ("Cruiser", 3),
    ("Submarine", 3),
    ("Destroyer", 2),
)
BATTLESHIP_COLS = "ABCDEFGHIJ"


def _battleship_path(game_id: str) -> Path:
    return _games_dir() / f"{_normalize_game_id(game_id)}.battleship.json"


def _battleship_coord_name(idx: int) -> str:
    row, col = divmod(idx, BATTLESHIP_SIZE)
    return f"{BATTLESHIP_COLS[col]}{row + 1}"


def _battleship_coord_idx(coordinate: str) -> int:
    text = (coordinate or "").strip().upper()
    if len(text) < 2 or text[0] not in BATTLESHIP_COLS or not text[1:].isdigit():
        raise ValueError(f"Coordinate {coordinate!r} must look like B7 (A-J, 1-10).")
    row = int(text[1:])
    if row < 1 or row > BATTLESHIP_SIZE:
        raise ValueError(f"Coordinate {coordinate!r} must look like B7 (A-J, 1-10).")
    return (row - 1) * BATTLESHIP_SIZE + BATTLESHIP_COLS.index(text[0])


def _battleship_random_fleet() -> list[dict[str, Any]]:
    taken: set[int] = set()
    fleet = []
    for name, length in BATTLESHIP_FLEET:
        while True:
            horizontal = random.random() < 0.5
            if horizontal:
                row = random.randrange(BATTLESHIP_SIZE)
                col = random.randrange(BATTLESHIP_SIZE - length + 1)
                cells = [row * BATTLESHIP_SIZE + col + i for i in range(length)]
            else:
                row = random.randrange(BATTLESHIP_SIZE - length + 1)
                col = random.randrange(BATTLESHIP_SIZE)
                cells = [(row + i) * BATTLESHIP_SIZE + col for i in range(length)]
            if not taken.intersection(cells):
                taken.update(cells)
                fleet.append({"name": name, "cells": cells, "hits": []})
                break
    return fleet


def _battleship_ship_at(fleet: list[dict[str, Any]], idx: int) -> dict[str, Any] | None:
    for ship in fleet:
        if idx in ship["cells"]:
            return ship
    return None


def _battleship_view(state: dict[str, Any], player: str) -> dict[str, Any]:
    """One player's honest, redacted view: own fleet + own shot results only."""
    opponent = _opponent(player)
    own_fleet = state["fleets"][player]
    incoming = state["shots"][opponent]
    outgoing = state["shots"][player]
    your_board = ["" for _ in range(BATTLESHIP_SIZE * BATTLESHIP_SIZE)]
    for ship in own_fleet:
        for cell in ship["cells"]:
            your_board[cell] = "ship"
    for coord, result in incoming.items():
        idx = int(coord)
        your_board[idx] = "ship-hit" if result in ("hit", "sunk") else "splash"
    target_board = ["" for _ in range(BATTLESHIP_SIZE * BATTLESHIP_SIZE)]
    for coord, result in outgoing.items():
        target_board[int(coord)] = result
    own_afloat = sum(1 for ship in own_fleet if len(ship["hits"]) < len(ship["cells"]))
    enemy_fleet = state["fleets"][opponent]
    enemy_sunk = [
        {"name": ship["name"], "size": len(ship["cells"])}
        for ship in enemy_fleet
        if len(ship["hits"]) >= len(ship["cells"])
    ]
    view = {
        "game_id": state["game_id"],
        "game": "battleship",
        "viewer": player,
        "turn": state["turn"],
        "status": state["status"],
        "winner": state["winner"],
        "your_board": your_board,
        "target_board": target_board,
        "your_ships_afloat": own_afloat,
        "enemy_ships_afloat": len(enemy_fleet) - len(enemy_sunk),
        "enemy_ships_sunk": enemy_sunk,
        "shots_fired": sum(1 for move in state["moves"] if move["player"] == player),
        # Shot counts give away nothing about positions, and they are the one
        # thing both sides can compare to see they are at the same table — in a
        # game with no shared board, "we are in different games" and "nobody has
        # fired yet" look identical without them.
        "opponent_shots_fired": sum(1 for move in state["moves"] if move["player"] == opponent),
        "last_move": state["moves"][-1] if state["moves"] else None,
        "error": state.get("error"),
    }
    if state.get("record_id"):
        view["record_id"] = state["record_id"]
        view["record_hint"] = state.get("record_hint")
    view["rendered_board"] = _render_battleship_view(view)
    return view


def _render_battleship_view(view: dict[str, Any]) -> str:
    symbols_target = {"hit": "✕", "sunk": "☒", "miss": "·", "": " "}
    symbols_own = {"ship": "▧", "ship-hit": "✕", "splash": "·", "": " "}

    def grid(board: list[str], symbols: dict[str, str]) -> list[str]:
        lines = ["    " + " ".join(BATTLESHIP_COLS)]
        for row in range(BATTLESHIP_SIZE):
            cells = " ".join(
                symbols[board[row * BATTLESHIP_SIZE + col]] for col in range(BATTLESHIP_SIZE)
            )
            lines.append(f"{row + 1:>2}  {cells}")
        return lines
    lines = [f"Battleship — {view['viewer']}'s private view. Fire with coordinates like B7."]
    lines.append("Enemy waters (your shots: ✕ hit, ☒ sunk, · miss):")
    lines.extend(grid(view["target_board"], symbols_target))
    lines.append("Your fleet (▧ ship, ✕ hit, · their miss):")
    lines.extend(grid(view["your_board"], symbols_own))
    lines.append(
        f"Ships afloat — yours: {view['your_ships_afloat']}, enemy: {view['enemy_ships_afloat']} | "
        f"turn: {view['turn']} | status: {view['status']}"
    )
    lines.append(
        f"Table {view['game_id']} — shots fired: you {view['shots_fired']}, "
        f"opponent {view['opponent_shots_fired']}."
    )
    return "\n".join(lines)


def battleship_save_game(state: dict[str, Any]) -> None:
    _battleship_path(state["game_id"]).write_text(
        json.dumps(state, indent=2, sort_keys=True), encoding="utf-8"
    )


def battleship_new_game(game_id: str = TABLE_BATTLESHIP) -> dict[str, Any]:
    """Start a battleship game with two freshly hidden random fleets."""
    state = {
        "game_id": _normalize_game_id(game_id),
        "game": "battleship",
        "fleets": {"human": _battleship_random_fleet(), "agent": _battleship_random_fleet()},
        "shots": {"human": {}, "agent": {}},
        "turn": "human",
        "status": "playing",
        "winner": None,
        "moves": [],
        "error": None,
    }
    battleship_save_game(state)
    return state


def _battleship_load(game_id: str) -> dict[str, Any]:
    path = _battleship_path(game_id)
    if not path.exists():
        return battleship_new_game(game_id=game_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("corrupt battleship state at %s; starting over", path)
        return battleship_new_game(game_id=game_id)


def battleship_get_view(game_id: str = TABLE_BATTLESHIP, player: str = "human") -> dict[str, Any]:
    """Load one player's redacted view of the game."""
    player = (player or "").strip().lower()
    if player not in PLAYERS:
        return {"state": "error", "label": "Player must be human or agent."}
    state = _battleship_load(game_id)
    state["error"] = None
    return _battleship_view(state, player)


def battleship_shuffle(game_id: str = TABLE_BATTLESHIP, player: str = "human") -> dict[str, Any]:
    """Re-randomize your own fleet, allowed only before any shot is fired."""
    player = (player or "").strip().lower()
    if player not in PLAYERS:
        return {"state": "error", "label": "Player must be human or agent."}
    state = _battleship_load(game_id)
    state["error"] = None
    if state["moves"]:
        state["error"] = "The battle has begun — fleets are committed."
        return _battleship_view(state, player)
    state["fleets"][player] = _battleship_random_fleet()
    battleship_save_game(state)
    return _battleship_view(state, player)


def battleship_fire(
    game_id: str = TABLE_BATTLESHIP, player: str = "human", coordinate: str = "A1"
) -> dict[str, Any]:
    """Fire one shot at the enemy grid. Turns alternate shot by shot."""
    player = (player or "").strip().lower()
    if player not in PLAYERS:
        return {"state": "error", "label": "Player must be human or agent."}
    state = _battleship_load(game_id)
    state["error"] = None

    if state["status"] != "playing":
        state["error"] = (
            f"Battle {state['game_id']} is already {state['status']}. "
            "Start a new game to play again."
        )
        return _battleship_view(state, player)
    if player != state["turn"]:
        state["error"] = f"It is {state['turn']}'s turn, not {player}'s."
        if not state["moves"] and player == "agent":
            state["error"] += (
                " The opening shot belongs to the 'human' seat. If two AI agents are "
                "playing each other, one of you has to sit in that seat: pass "
                "player='human' on every battleship call for that side."
            )
        return _battleship_view(state, player)

    try:
        idx = _battleship_coord_idx(coordinate)
    except ValueError as exc:
        state["error"] = str(exc)
        return _battleship_view(state, player)

    if str(idx) in state["shots"][player]:
        state["error"] = f"You already fired at {_battleship_coord_name(idx)}."
        return _battleship_view(state, player)

    opponent = _opponent(player)
    ship = _battleship_ship_at(state["fleets"][opponent], idx)
    if ship is None:
        result = "miss"
    else:
        if idx not in ship["hits"]:
            ship["hits"].append(idx)
        if len(ship["hits"]) >= len(ship["cells"]):
            result = "sunk"
            for cell in ship["cells"]:
                state["shots"][player][str(cell)] = "sunk"
        else:
            result = "hit"
    state["shots"][player][str(idx)] = result
    move = {"player": player, "coordinate": _battleship_coord_name(idx), "result": result}
    if result == "sunk":
        move["ship"] = ship["name"]
        move["size"] = len(ship["cells"])
    state["moves"].append(move)

    if all(len(s["hits"]) >= len(s["cells"]) for s in state["fleets"][opponent]):
        state["status"] = "won"
        state["winner"] = player
        shots = sum(1 for m in state["moves"] if m["player"] == player)
        _record_result(state, f"sank the whole fleet in {shots} shots")
    else:
        state["turn"] = opponent

    battleship_save_game(state)
    return _battleship_view(state, player)


# ── House records: the Game Room ledger ──────────────────────────────────────
MAX_RECORDS = 300


def _records_path() -> Path:
    return _games_dir() / "records.json"


def _load_records() -> list[dict[str, Any]]:
    path = _records_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("corrupt records at %s; starting a fresh ledger", path)
        return []
    records = data.get("records") if isinstance(data, dict) else None
    return records if isinstance(records, list) else []


def _save_records(records: list[dict[str, Any]]) -> None:
    _records_path().write_text(
        json.dumps({"records": records[-MAX_RECORDS:]}, indent=2), encoding="utf-8"
    )


def _record_result(state: dict[str, Any], detail: str | None = None) -> None:
    """Write one finished game into the ledger and stamp the state with its id."""
    record = {
        "id": uuid.uuid4().hex[:10],
        "game": state.get("game"),
        "game_id": state.get("game_id"),
        "result": state.get("status"),
        "winner": state.get("winner"),
        "moves": len(state.get("moves") or []),
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "detail": detail,
        "title": None,
        "note": None,
    }
    records = _load_records()
    records.append(record)
    _save_records(records)
    state["record_id"] = record["id"]
    state["record_hint"] = (
        f"Match recorded in the house ledger (record_id {record['id']}). "
        "Use gameroom_annotate to give it a title and a postgame note."
    )


def gameroom_annotate(record_id: str = "", title: str = "", note: str = "") -> dict[str, Any]:
    """Attach a match title and/or postgame note to one ledger record."""
    records = _load_records()
    for record in records:
        if record.get("id") == (record_id or "").strip():
            if title.strip():
                record["title"] = title.strip()[:160]
            if note.strip():
                record["note"] = note.strip()[:400]
            _save_records(records)
            return {"state": "live", "record": record}
    return {"state": "error", "label": f"No ledger record with id {record_id!r}."}


def gameroom_records() -> dict[str, Any]:
    """Return the ledger plus computed standings for the Game Room lobby."""
    records = _load_records()
    per_game: dict[str, dict[str, int]] = {}
    score = {"human": 0, "agent": 0, "draws": 0}
    for record in records:
        game = str(record.get("game") or "unknown")
        tally = per_game.setdefault(game, {"human": 0, "agent": 0, "draws": 0})
        winner = record.get("winner")
        if winner in ("human", "agent"):
            tally[winner] += 1
            score[winner] += 1
        else:
            tally["draws"] += 1
            score["draws"] += 1
    streak = {"player": None, "count": 0}
    for record in reversed(records):
        winner = record.get("winner")
        if winner not in ("human", "agent"):
            break
        if streak["player"] is None:
            streak = {"player": winner, "count": 1}
        elif streak["player"] == winner:
            streak["count"] += 1
        else:
            break
    longest = max(records, key=lambda r: r.get("moves") or 0, default=None)
    return {
        "state": "live" if records else "empty",
        "records": list(reversed(records[-40:])),
        "stats": {
            "score": score,
            "per_game": per_game,
            "streak": streak,
            "longest": {
                "game": longest.get("game"),
                "moves": longest.get("moves"),
                "title": longest.get("title"),
                "winner": longest.get("winner"),
            } if longest else None,
            "total_matches": len(records),
        },
    }


def _json_result(state: dict[str, Any]) -> str:
    return json.dumps(state, indent=2, sort_keys=True)


RESUME_NOTE = (
    "A game is already under way at this table and this is where it stands — "
    "nothing was reset. Carry on from here, or call again with reset=True to "
    "abandon it and deal a fresh one."
)


def _game_under_way(path: Path, loader: Any, game_id: str) -> dict[str, Any] | None:
    """Return the game being played at this table, or None if nothing is going on.

    Dealing a fresh game over a live one throws it away without a word, which is
    worst in battleship: both fleets are re-rolled, so each side is left holding
    notes on ships that no longer exist. A table nobody has moved on yet is fair
    game — it is the one in play we protect.
    """
    if not path.exists():
        return None
    state = loader(game_id)
    if state.get("status") != "playing" or not state.get("moves"):
        return None
    return state


def create_mcp_server() -> "FastMCP":
    """Create the Game Master MCP server."""
    if not _MCP_SERVER_AVAILABLE:
        raise ImportError(
            "Game Master MCP server requires the 'mcp' package. "
            f"Install with: {sys.executable} -m pip install 'mcp'"
        )

    mcp = FastMCP(
        "game-master",
        instructions=(
            "Game Master. Use these tools to start, inspect, and play shared "
            "board games between the human and you, the agent: tic-tac-toe, "
            "Connect Four, checkers, backgammon, chess (the human is White), "
            "and battleship (each player sees only their own redacted view — "
            "no peeking). You always play as 'agent'; the human plays as "
            "'human'. If your opponent is another AI rather than a person, one "
            "of you must take the 'human' seat — pass player='human' on every "
            "call for that side. Every tool already defaults to the table the "
            "bundled web Game Room shows (room-tictactoe, room-connect4, "
            "room-checkers, room-backgammon, room-chess, room-battleship), so "
            "you and the person you are playing sit at the same board without "
            "either of you naming it; pass a game_id only to run a second, "
            "separate game. Starting a game will not throw away one already in "
            "progress: you get that game back instead, and reset=True is there "
            "if you truly mean to abandon it. Finished games land in the house "
            "ledger automatically; when one does, the result includes a "
            "record_id — use gameroom_annotate_match to give the match a title "
            "and a postgame note worthy of the wall."
        ),
    )

    @mcp.tool()
    def game_new(
        game_id: str = TABLE_TICTACTOE,
        human_mark: str = "X",
        agent_mark: str = "O",
        reset: bool = False,
    ) -> str:
        """Start a tic-tac-toe game.

        Args:
            game_id: Which table to play at; the default is the room's.
            human_mark: Human's board mark. Defaults to X.
            agent_mark: Agent's board mark. Defaults to O.
            reset: Throw away a game already in progress here. Off by default.
        """
        live = _game_under_way(_game_path(game_id), load_game, game_id)
        if live is not None and not reset:
            return _json_result({**live, "error": RESUME_NOTE})
        return _json_result(new_game(game_id=game_id, human_mark=human_mark, agent_mark=agent_mark))

    @mcp.tool()
    def game_get_state(game_id: str = TABLE_TICTACTOE) -> str:
        """Return the current tic-tac-toe game state."""
        return _json_result(load_game(game_id=game_id))

    @mcp.tool()
    def game_submit_move(game_id: str = TABLE_TICTACTOE, player: str = "human", position: int = 1) -> str:
        """Submit a tic-tac-toe move.

        Args:
            game_id: Which table to play at; the default is the room's.
            player: human or agent.
            position: Board square 1-9.
        """
        return _json_result(submit_move(game_id=game_id, player=player, position=position))

    @mcp.tool()
    def backgammon_new(game_id: str = TABLE_BACKGAMMON, reset: bool = False) -> str:
        """Start a backgammon game.

        Args:
            game_id: Which table to play at; the default is the room's.
            reset: Throw away a game already in progress here. Off by default.
        """
        live = _game_under_way(_backgammon_path(game_id), backgammon_load_game, game_id)
        if live is not None and not reset:
            return _json_result({**live, "error": RESUME_NOTE})
        return _json_result(backgammon_new_game(game_id=game_id))

    @mcp.tool()
    def backgammon_get_state(game_id: str = TABLE_BACKGAMMON) -> str:
        """Return the current backgammon game state."""
        return _json_result(backgammon_load_game(game_id=game_id))

    @mcp.tool()
    def backgammon_roll(
        game_id: str = TABLE_BACKGAMMON,
        player: str = "human",
        die1: int | None = None,
        die2: int | None = None,
    ) -> str:
        """Roll backgammon dice for the current player.

        Args:
            game_id: Which table to play at; the default is the room's.
            player: human or agent.
            die1: Optional explicit first die for demos/tests. Omit for random.
            die2: Optional explicit second die for demos/tests. Omit for random.
        """
        return _json_result(
            globals()["backgammon_roll"](game_id=game_id, player=player, die1=die1, die2=die2)
        )

    @mcp.tool()
    def backgammon_move(
        game_id: str = TABLE_BACKGAMMON,
        player: str = "human",
        from_point: int = 24,
        to_point: int = 23,
    ) -> str:
        """Move one backgammon checker using an available die.

        Args:
            game_id: Which table to play at; the default is the room's.
            player: human or agent.
            from_point: Source point number 1-24.
            to_point: Destination point number 1-24.
        """
        return _json_result(
            globals()["backgammon_move"](
                game_id=game_id, player=player, from_point=from_point, to_point=to_point
            )
        )

    @mcp.tool()
    def backgammon_enter(game_id: str = TABLE_BACKGAMMON, player: str = "human", to_point: int = 24) -> str:
        """Enter a checker from the bar using an available die.

        Args:
            game_id: Which table to play at; the default is the room's.
            player: human or agent.
            to_point: Entry point. Human enters on 24-19, Agent on 1-6.
        """
        return _json_result(
            globals()["backgammon_enter"](game_id=game_id, player=player, to_point=to_point)
        )

    @mcp.tool()
    def backgammon_bear_off(game_id: str = TABLE_BACKGAMMON, player: str = "human", from_point: int = 1) -> str:
        """Bear a checker off once every checker is in the home board.

        Args:
            game_id: Which table to play at; the default is the room's.
            player: human or agent.
            from_point: Point to bear off from. Human's home is 1-6, Agent's is 19-24.
        """
        return _json_result(
            globals()["backgammon_bear_off"](game_id=game_id, player=player, from_point=from_point)
        )

    @mcp.tool()
    def backgammon_end_turn(game_id: str = TABLE_BACKGAMMON, player: str = "human") -> str:
        """End the current backgammon turn and discard unused dice.

        Args:
            game_id: Which table to play at; the default is the room's.
            player: human or agent.
        """
        return _json_result(globals()["backgammon_end_turn"](game_id=game_id, player=player))

    @mcp.tool()
    def connect4_new(game_id: str = TABLE_CONNECT4, reset: bool = False) -> str:
        """Start a Connect Four game.

        Args:
            game_id: Which table to play at; the default is the room's.
            reset: Throw away a game already in progress here. Off by default.
        """
        live = _game_under_way(_connect4_path(game_id), connect4_load_game, game_id)
        if live is not None and not reset:
            return _json_result({**live, "error": RESUME_NOTE})
        return _json_result(connect4_new_game(game_id=game_id))

    @mcp.tool()
    def connect4_get_state(game_id: str = TABLE_CONNECT4) -> str:
        """Return the current Connect Four game state."""
        return _json_result(connect4_load_game(game_id=game_id))

    @mcp.tool()
    def connect4_drop(game_id: str = TABLE_CONNECT4, player: str = "human", column: int = 1) -> str:
        """Drop a Connect Four checker into a column.

        Args:
            game_id: Which table to play at; the default is the room's.
            player: human or agent.
            column: Column 1-7, left to right.
        """
        return _json_result(
            globals()["connect4_drop"](game_id=game_id, player=player, column=column)
        )

    @mcp.tool()
    def checkers_new(game_id: str = TABLE_CHECKERS, reset: bool = False) -> str:
        """Start a checkers game.

        Args:
            game_id: Which table to play at; the default is the room's.
            reset: Throw away a game already in progress here. Off by default.
        """
        live = _game_under_way(_checkers_path(game_id), checkers_load_game, game_id)
        if live is not None and not reset:
            return _json_result({**live, "error": RESUME_NOTE})
        return _json_result(checkers_new_game(game_id=game_id))

    @mcp.tool()
    def checkers_get_state(game_id: str = TABLE_CHECKERS) -> str:
        """Return the current checkers game state."""
        return _json_result(checkers_load_game(game_id=game_id))

    @mcp.tool()
    def chess_new(game_id: str = TABLE_CHESS, reset: bool = False) -> str:
        """Start a chess game. Human is White and moves first.

        Args:
            game_id: Which table to play at; the default is the room's.
            reset: Throw away a game already in progress here. Off by default.
        """
        live = _game_under_way(_chess_path(game_id), chess_load_game, game_id)
        if live is not None and not reset:
            return _json_result({**live, "error": RESUME_NOTE})
        return _json_result(chess_new_game(game_id=game_id))

    @mcp.tool()
    def chess_get_state(game_id: str = TABLE_CHESS) -> str:
        """Return the current chess state, including all legal moves for the side to move."""
        return _json_result(chess_load_game(game_id=game_id))

    @mcp.tool()
    def chess_move(
        game_id: str = TABLE_CHESS,
        player: str = "human",
        from_square: str = "e2",
        to_square: str = "e4",
        promotion: str = "q",
    ) -> str:
        """Play one chess move with algebraic squares (e2 → e4).

        Castle by moving the king two squares. Promotion is q, r, b, or n.

        Args:
            game_id: Which table to play at; the default is the room's.
            player: human or agent.
            from_square: Source square such as e2.
            to_square: Destination square such as e4.
            promotion: Piece for a promoting pawn; queen by default.
        """
        return _json_result(chess_submit_move(
            game_id=game_id, player=player, from_square=from_square,
            to_square=to_square, promotion=promotion,
        ))

    @mcp.tool()
    def battleship_new(game_id: str = TABLE_BATTLESHIP, reset: bool = False) -> str:
        """Start a battleship game with two hidden, randomly placed fleets.

        The 'human' seat fires first. Playing another AI instead of a person?
        One of you must take the 'human' seat on every battleship call.

        Args:
            game_id: Which table to play at. The default is the table the
                web Game Room shows, which is almost always what you
                want. Only name another to run a separate game.
            reset: Throw away a battle already in progress here, re-rolling
                both fleets. Off by default.
        """
        live = _game_under_way(_battleship_path(game_id), _battleship_load, game_id)
        if live is not None and not reset:
            view = _battleship_view(live, "agent")
            view["error"] = RESUME_NOTE
            return _json_result(view)
        state = battleship_new_game(game_id=game_id)
        return _json_result(_battleship_view(state, "agent"))

    @mcp.tool()
    def battleship_get_state(game_id: str = TABLE_BATTLESHIP, player: str = "agent") -> str:
        """Return one player's redacted battleship view (own fleet + own shot results).

        Args:
            game_id: Which table to play at; the default is the room's.
            player: Whose private view to load. Only ask for your own — if you
                are the side holding the 'human' seat, that means
                player='human'.
        """
        return _json_result(battleship_get_view(game_id=game_id, player=player))

    @mcp.tool()
    def battleship_fire_shot(game_id: str = TABLE_BATTLESHIP, player: str = "agent", coordinate: str = "A1") -> str:
        """Fire one shot at the enemy grid (A-J columns, rows 1-10, like B7).

        Args:
            game_id: Which table to play at; the default is the room's.
            player: Your own seat, human or agent. The 'human' seat fires
                first, so in an AI-vs-AI game one side passes player='human'
                throughout.
            coordinate: Target square such as B7.
        """
        return _json_result(battleship_fire(game_id=game_id, player=player, coordinate=coordinate))

    @mcp.tool()
    def battleship_shuffle_fleet(game_id: str = TABLE_BATTLESHIP, player: str = "agent") -> str:
        """Re-randomize your own fleet placement, allowed only before the first shot.

        Args:
            game_id: Which table to play at; the default is the room's.
            player: Your own seat, human or agent.
        """
        return _json_result(battleship_shuffle(game_id=game_id, player=player))

    @mcp.tool()
    def gameroom_ledger() -> str:
        """Read the Game Room house ledger: standings, streaks, and match records."""
        return _json_result(gameroom_records())

    @mcp.tool()
    def gameroom_annotate_match(record_id: str = "", title: str = "", note: str = "") -> str:
        """Give a finished match its title and postgame note in the house ledger.

        Args:
            record_id: The ledger record id reported when the game finished.
            title: A short match title for the wall.
            note: The postgame color commentary.
        """
        return _json_result(gameroom_annotate(record_id=record_id, title=title, note=note))

    @mcp.tool()
    def checkers_submit_move(
        game_id: str = TABLE_CHECKERS,
        player: str = "human",
        from_square: int = 1,
        to_square: int = 1,
    ) -> str:
        """Move a checkers piece. Captures are mandatory; keep jumping while you can.

        Args:
            game_id: Which table to play at; the default is the room's.
            player: human or agent.
            from_square: Source square 1-64, left to right from the top row.
            to_square: Destination square 1-64.
        """
        return _json_result(
            checkers_move(
                game_id=game_id, player=player, from_square=from_square, to_square=to_square
            )
        )

    return mcp


def main(argv: Optional[list[str]] = None) -> int:
    argv = argv or sys.argv[1:]
    verbose = "--verbose" in argv or "-v" in argv
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        stream=sys.stderr,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        server = create_mcp_server()
    except ImportError as exc:
        sys.stderr.write(f"game master MCP server cannot start: {exc}\n")
        return 2

    try:
        server.run()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        logger.exception("game master MCP server crashed")
        sys.stderr.write(f"game master MCP server error: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
