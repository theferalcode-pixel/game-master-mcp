#!/usr/bin/env python3
"""The Game Room — a small local web server for playing at the Game Master's tables.

Serves the web/ pages, relays game actions to game_master.py, exposes the house
ledger, and (optionally) relays one chat session to a local agent chat server so
your AI can sit beside the board.

Configuration comes from config.json next to this file (see config.example.json)
with environment variables taking precedence:

    GAME_ROOM_HOST          default 127.0.0.1
    GAME_ROOM_PORT          default 8777
    GAME_MASTER_HOME        where game state lives; default ~/.game-master
    GAME_ROOM_PLAYER_NAME   display name for the human seat; default "Player"
    GAME_ROOM_AGENT_NAME    display name for the AI seat; default "Agent"
    GAME_ROOM_THEME         default color scheme: hearth, tide, or grove
    GAME_ROOM_CHAT_URL      optional chat server to relay (see README); empty = chat panel off
    GAME_ROOM_CHAT_PROFILE  optional profile name sent with chat messages
    GAME_ROOM_CHAT_WORKSPACE optional workspace path sent with chat messages
"""

from __future__ import annotations

import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"


def _file_config() -> dict:
    path = APP_DIR / "config.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


_FILE_CONFIG = _file_config()


def _setting(env_key: str, file_key: str, default: str) -> str:
    return os.environ.get(env_key) or str(_FILE_CONFIG.get(file_key) or "") or default


PLAYER_NAME = _setting("GAME_ROOM_PLAYER_NAME", "player_name", "Player")[:40]
AGENT_NAME = _setting("GAME_ROOM_AGENT_NAME", "agent_name", "Agent")[:40]
DEFAULT_THEME = _setting("GAME_ROOM_THEME", "theme", "hearth")
CHAT_BASE = _setting("GAME_ROOM_CHAT_URL", "chat_url", "").rstrip("/")
CHAT_PROFILE = _setting("GAME_ROOM_CHAT_PROFILE", "chat_profile", "")
CHAT_WORKSPACE = _setting("GAME_ROOM_CHAT_WORKSPACE", "chat_workspace", "")
CHAT_SESSION_PATH = APP_DIR / ".gameroom-chat.json"
CHAT_OFFLINE_LABEL = "The chat server is not reachable right now."

if os.environ.get("GAME_MASTER_HOME") is None and _FILE_CONFIG.get("data_home"):
    os.environ["GAME_MASTER_HOME"] = str(_FILE_CONFIG["data_home"])
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
import game_master


def _tictactoe_action(game_id: str, payload: dict) -> dict:
    action = payload.get("action")
    if action == "new":
        return game_master.new_game(game_id=game_id)
    if action == "move":
        return game_master.submit_move(
            game_id=game_id, player="human", position=payload.get("position")
        )
    return {"state": "error", "label": "Action must be 'new' or 'move'."}


def _connect4_action(game_id: str, payload: dict) -> dict:
    action = payload.get("action")
    if action == "new":
        return game_master.connect4_new_game(game_id=game_id)
    if action == "drop":
        return game_master.connect4_drop(
            game_id=game_id, player="human", column=payload.get("column")
        )
    return {"state": "error", "label": "Action must be 'new' or 'drop'."}


def _checkers_action(game_id: str, payload: dict) -> dict:
    action = payload.get("action")
    if action == "new":
        return game_master.checkers_new_game(game_id=game_id)
    if action == "move":
        return game_master.checkers_move(
            game_id=game_id,
            player="human",
            from_square=payload.get("from_square"),
            to_square=payload.get("to_square"),
        )
    return {"state": "error", "label": "Action must be 'new' or 'move'."}


def _backgammon_action(game_id: str, payload: dict) -> dict:
    action = payload.get("action")
    if action == "new":
        return game_master.backgammon_new_game(game_id=game_id)
    if action == "roll":
        return game_master.backgammon_roll(game_id=game_id, player="human")
    if action == "move":
        return game_master.backgammon_move(
            game_id=game_id,
            player="human",
            from_point=payload.get("from_point"),
            to_point=payload.get("to_point"),
        )
    if action == "enter":
        return game_master.backgammon_enter(
            game_id=game_id, player="human", to_point=payload.get("to_point")
        )
    if action == "bear_off":
        return game_master.backgammon_bear_off(
            game_id=game_id, player="human", from_point=payload.get("from_point")
        )
    if action == "end_turn":
        return game_master.backgammon_end_turn(game_id=game_id, player="human")
    return {
        "state": "error",
        "label": "Action must be one of new, roll, move, enter, bear_off, end_turn.",
    }


def _chess_action(game_id: str, payload: dict) -> dict:
    action = payload.get("action")
    if action == "new":
        return game_master.chess_new_game(game_id=game_id)
    if action == "move":
        return game_master.chess_submit_move(
            game_id=game_id,
            player="human",
            from_square=str(payload.get("from_square", "")),
            to_square=str(payload.get("to_square", "")),
            promotion=str(payload.get("promotion", "q")),
        )
    return {"state": "error", "label": "Action must be 'new' or 'move'."}


def _battleship_load(game_id: str) -> dict:
    """The browser only ever receives the human's redacted view of the battle."""
    return game_master.battleship_get_view(game_id=game_id, player="human")


def _battleship_action(game_id: str, payload: dict) -> dict:
    action = payload.get("action")
    if action == "new":
        state = game_master.battleship_new_game(game_id=game_id)
        return game_master._battleship_view(state, "human")
    if action == "fire":
        return game_master.battleship_fire(
            game_id=game_id, player="human", coordinate=str(payload.get("coordinate", ""))
        )
    if action == "shuffle":
        return game_master.battleship_shuffle(game_id=game_id, player="human")
    return {"state": "error", "label": "Action must be 'new', 'fire', or 'shuffle'."}


# The room's tables are the game master's default tables, so a person can open
# a board here, say "your turn" to their AI, and both end up at the same game
# without anyone naming a table.
WEB_GAMES = {
    "tic-tac-toe": {"game_id": game_master.TABLE_TICTACTOE, "load": game_master.load_game, "act": _tictactoe_action},
    "connect-four": {"game_id": game_master.TABLE_CONNECT4, "load": game_master.connect4_load_game, "act": _connect4_action},
    "checkers": {"game_id": game_master.TABLE_CHECKERS, "load": game_master.checkers_load_game, "act": _checkers_action},
    "backgammon": {"game_id": game_master.TABLE_BACKGAMMON, "load": game_master.backgammon_load_game, "act": _backgammon_action},
    "chess": {"game_id": game_master.TABLE_CHESS, "load": game_master.chess_load_game, "act": _chess_action},
    "battleship": {"game_id": game_master.TABLE_BATTLESHIP, "load": _battleship_load, "act": _battleship_action},
}


def game_payload(game_name: str) -> dict:
    game = WEB_GAMES[game_name]
    return game["load"](game["game_id"])


def game_action(game_name: str, payload: dict) -> dict:
    game = WEB_GAMES[game_name]
    return game["act"](game["game_id"], payload)


# ── Optional chat relay ──────────────────────────────────────────────────────
# The chat panel expects a local server speaking the Hermes WebUI chat API
# (POST /api/session/new, POST /api/chat/start → stream_id, SSE
# GET /api/chat/stream, GET /api/session). Leave GAME_ROOM_CHAT_URL empty to
# run the room without a chat panel; the games work fine either way.
class ChatProxyError(Exception):
    def __init__(self, label: str, status: int = 502):
        super().__init__(label)
        self.label = label
        self.status = status


def _chat_enabled() -> bool:
    return bool(CHAT_BASE)


def _hermes_request(path: str, payload: dict | None = None, timeout: int = 30) -> dict:
    import urllib.error
    import urllib.request

    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        CHAT_BASE + path,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", "")
        except Exception:
            detail = ""
        raise ChatProxyError(detail or f"Chat server error {exc.code}", exc.code) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ChatProxyError(CHAT_OFFLINE_LABEL) from exc
    except json.JSONDecodeError as exc:
        raise ChatProxyError("The chat server sent an unreadable reply.") from exc


def _stored_chat_session() -> str | None:
    try:
        return json.loads(CHAT_SESSION_PATH.read_text(encoding="utf-8")).get("session_id")
    except (OSError, json.JSONDecodeError):
        return None


def _create_chat_session() -> str:
    body = {"title": "Game Room"}
    if CHAT_WORKSPACE:
        body["workspace"] = CHAT_WORKSPACE
    data = _hermes_request("/api/session/new", body)
    session_id = (data.get("session") or {}).get("session_id")
    if not session_id:
        raise ChatProxyError("The chat server did not return a session.")
    CHAT_SESSION_PATH.write_text(json.dumps({"session_id": session_id}), encoding="utf-8")
    return session_id


def chat_send(payload: dict) -> dict:
    if not _chat_enabled():
        raise ChatProxyError("Chat is not configured for this Game Room.", 400)
    message = str(payload.get("message", "")).strip()
    if not message:
        raise ChatProxyError("Say something first.", 400)
    if len(message) > 16000:
        raise ChatProxyError("That message is too long for the table.", 400)
    session_id = _stored_chat_session() or _create_chat_session()
    body = {"session_id": session_id, "message": message}
    if CHAT_PROFILE:
        body["profile"] = CHAT_PROFILE
    if CHAT_WORKSPACE:
        body["workspace"] = CHAT_WORKSPACE
    try:
        data = _hermes_request("/api/chat/start", body)
    except ChatProxyError as exc:
        if exc.status != 404:
            raise
        session_id = _create_chat_session()
        body["session_id"] = session_id
        data = _hermes_request("/api/chat/start", body)
    stream_id = data.get("stream_id")
    if not stream_id:
        raise ChatProxyError("The chat server accepted the message but sent no stream.")
    return {"state": "live", "session_id": session_id, "stream_id": stream_id}


def _chat_history_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for piece in content:
            if isinstance(piece, dict) and isinstance(piece.get("text"), str):
                parts.append(piece["text"])
        return "\n".join(parts)
    return ""


def chat_history(limit: int = 40) -> dict:
    if not _chat_enabled():
        return {"state": "disabled", "messages": []}
    session_id = _stored_chat_session()
    if not session_id:
        return {"state": "empty", "messages": []}
    try:
        data = _hermes_request(f"/api/session?session_id={session_id}&msg_limit={int(limit)}")
    except ChatProxyError as exc:
        if exc.status == 404:
            return {"state": "empty", "messages": []}
        raise
    raw = (data.get("session") or {}).get("messages") or []
    messages = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        if role not in ("user", "assistant"):
            continue
        text = _chat_history_text(entry.get("content")).strip()
        if text:
            messages.append({"role": role, "content": text})
    return {"state": "live", "session_id": session_id, "messages": messages}


class GameRoomHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def send_bytes(self, content: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, payload: dict, status: int = 200) -> None:
        self.send_bytes(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            status,
        )

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        if route == "/api/config":
            self.send_json({
                "player_name": PLAYER_NAME,
                "agent_name": AGENT_NAME,
                "theme": DEFAULT_THEME,
                "chat_enabled": _chat_enabled(),
            })
            return
        if route.startswith("/api/games/"):
            game_name = route.removeprefix("/api/games/")
            if game_name not in WEB_GAMES:
                self.send_json({"state": "error", "label": "Unknown game"}, 404)
                return
            try:
                self.send_json(game_payload(game_name))
            except Exception as exc:
                self.send_json({"state": "error", "label": "Game master unavailable", "error": str(exc)}, 500)
            return
        if route == "/api/gameroom/records":
            try:
                self.send_json(game_master.gameroom_records())
            except Exception as exc:
                self.send_json({"state": "error", "label": "Ledger unavailable", "error": str(exc)}, 500)
            return
        if route == "/api/chat/history":
            try:
                self.send_json(chat_history())
            except ChatProxyError as exc:
                self.send_json({"state": "error", "label": exc.label}, exc.status)
            except Exception as exc:
                self.send_json({"state": "error", "label": "Chat history unavailable", "error": str(exc)}, 500)
            return
        if route == "/api/chat/stream":
            stream_id = (parse_qs(parsed.query).get("stream_id") or [""])[0]
            self.relay_chat_stream(stream_id)
            return
        super().do_GET()

    def relay_chat_stream(self, stream_id: str) -> None:
        """Relay one chat SSE reply stream to the browser as it arrives."""
        import urllib.error
        import urllib.parse
        import urllib.request

        def send_sse_error(label: str) -> None:
            body = f"event: apperror\ndata: {json.dumps({'message': label})}\n\n"
            self.send_bytes(body.encode("utf-8"), "text/event-stream; charset=utf-8")

        if not _chat_enabled():
            send_sse_error("Chat is not configured for this Game Room.")
            return
        if not stream_id:
            send_sse_error("stream_id is required")
            return
        url = f"{CHAT_BASE}/api/chat/stream?stream_id={urllib.parse.quote(stream_id)}"
        try:
            upstream = urllib.request.urlopen(url, timeout=600)
        except (urllib.error.URLError, OSError) as exc:
            send_sse_error(
                f"Chat server error {exc.code}"
                if isinstance(exc, urllib.error.HTTPError)
                else CHAT_OFFLINE_LABEL
            )
            return
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            while True:
                chunk = upstream.read1(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            pass
        finally:
            upstream.close()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        game_name = route.removeprefix("/api/games/") if route.startswith("/api/games/") else None
        if game_name not in WEB_GAMES and route != "/api/chat/send":
            self.send_json({"state": "error", "label": "Route not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 32768:
                raise ValueError("Request is too large.")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Request must be a JSON object.")
            if route == "/api/chat/send":
                result = chat_send(payload)
            else:
                result = game_action(game_name, payload)
            status = 400 if result.get("state") == "error" else 200
            self.send_json(result, status)
        except ChatProxyError as exc:
            self.send_json({"state": "error", "label": exc.label}, exc.status)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"state": "error", "label": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"state": "error", "label": "Game master unavailable", "error": str(exc)}, 500)


def main() -> None:
    host = os.environ.get("GAME_ROOM_HOST", str(_FILE_CONFIG.get("host") or "127.0.0.1"))
    port = int(os.environ.get("GAME_ROOM_PORT", _FILE_CONFIG.get("port") or 8777))
    server = ThreadingHTTPServer((host, port), GameRoomHandler)
    chat_note = "chat relay on" if _chat_enabled() else "chat panel off (no GAME_ROOM_CHAT_URL)"
    print(f"Game Room open at http://{host}:{port}/ — {chat_note}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
