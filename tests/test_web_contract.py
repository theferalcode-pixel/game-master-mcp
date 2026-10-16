"""Contract checks for the web Game Room: honest boards, redacted battleship."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
server = (ROOT / "server.py").read_text(encoding="utf-8")
lobby = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
table = (ROOT / "web" / "game.html").read_text(encoding="utf-8")
js = (ROOT / "web" / "game.js").read_text(encoding="utf-8")


def test_every_game_has_a_shelf_box():
    for slug in ("tic-tac-toe", "connect-four", "checkers", "backgammon", "chess", "battleship"):
        assert f'href="./game.html?g={slug}"' in lobby


def test_room_tables_are_the_game_masters_default_tables(tmp_path, monkeypatch):
    """A person opening a board here and an AI using its tool defaults must land
    at the same table, without either of them naming one."""
    monkeypatch.setenv("GAME_MASTER_HOME", str(tmp_path))
    import inspect

    import game_master
    import server as room

    defaults = {
        "tic-tac-toe": game_master.load_game,
        "connect-four": game_master.connect4_load_game,
        "checkers": game_master.checkers_load_game,
        "backgammon": game_master.backgammon_load_game,
        "chess": game_master.chess_load_game,
        "battleship": game_master.battleship_get_view,
    }
    for slug, loader in defaults.items():
        tool_default = inspect.signature(loader).parameters["game_id"].default
        assert room.WEB_GAMES[slug]["game_id"] == tool_default, slug


def test_browser_only_acts_as_the_human_seat():
    assert 'player="human"' in server
    assert 'player="agent"' not in server
    assert "state.turn === 'human'" in js


def test_battleship_browser_view_is_redacted():
    assert 'battleship_get_view(game_id=game_id, player="human")' in server


def test_ledger_and_config_routes_exist():
    assert '"/api/gameroom/records"' in server
    assert '"/api/config"' in server
    assert 'id="recordsStats"' in lobby
    assert 'id="chatLog"' in table
