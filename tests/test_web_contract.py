"""Contract checks for the web Game Room: honest boards, redacted battleship."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
server = (ROOT / "server.py").read_text(encoding="utf-8")
lobby = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
table = (ROOT / "web" / "game.html").read_text(encoding="utf-8")
js = (ROOT / "web" / "game.js").read_text(encoding="utf-8")


def test_every_game_has_a_dedicated_table_and_shelf_box():
    for web_id in (
        "room-tictactoe", "room-connect4", "room-checkers",
        "room-backgammon", "room-chess", "room-battleship",
    ):
        assert f'"{web_id}"' in server
    for slug in ("tic-tac-toe", "connect-four", "checkers", "backgammon", "chess", "battleship"):
        assert f'href="./game.html?g={slug}"' in lobby


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
