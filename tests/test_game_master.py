import asyncio
import inspect
import json

import pytest


class _FakeTool:
    def __init__(self, fn):
        self.name = fn.__name__
        self.description = inspect.getdoc(fn) or ""
        self.fn = fn


class _FakeToolManager:
    def __init__(self):
        self._tools = {}

    def add_tool(self, fn):
        self._tools[fn.__name__] = _FakeTool(fn)

    async def call_tool(self, name, args=None):
        return self._tools[name].fn(**(args or {}))

    def list_tools(self):
        return list(self._tools.values())


class _FakeFastMCP:
    def __init__(self, *args, **kwargs):
        self._tool_manager = _FakeToolManager()

    def tool(self):
        def decorator(fn):
            self._tool_manager.add_tool(fn)
            return fn

        return decorator


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("GAME_MASTER_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def fake_server(monkeypatch):
    import game_master

    monkeypatch.setattr(game_master, "_MCP_SERVER_AVAILABLE", True)
    monkeypatch.setattr(game_master, "FastMCP", _FakeFastMCP)
    return game_master.create_mcp_server()


class TestGameLogic:
    def test_new_game_creates_empty_board_and_persists_state(self, tmp_path):
        import game_master

        state = game_master.new_game(game_id="porch", human_mark="X", agent_mark="O")

        assert state["game_id"] == "porch"
        assert state["board"] == ["", "", "", "", "", "", "", "", ""]
        assert state["turn"] == "human"
        assert state["status"] == "playing"
        assert state["winner"] is None

        persisted = game_master.load_game("porch")
        assert persisted == state

    def test_submit_move_places_mark_and_alternates_turn(self):
        import game_master

        game_master.new_game(game_id="porch")
        state = game_master.submit_move(game_id="porch", player="human", position=5)

        assert state["board"][4] == "X"
        assert state["turn"] == "agent"
        assert state["status"] == "playing"

    def test_rejects_wrong_turn_and_occupied_square(self):
        import game_master

        game_master.new_game(game_id="porch")
        first = game_master.submit_move(game_id="porch", player="human", position=1)
        wrong_turn = game_master.submit_move(game_id="porch", player="human", position=2)
        occupied = game_master.submit_move(game_id="porch", player="agent", position=1)

        assert first["error"] is None
        assert wrong_turn["error"] == "It is agent's turn, not human's."
        assert occupied["error"] == "Square 1 is already occupied."

    def test_detects_win_and_blocks_late_moves(self):
        import game_master

        game_master.new_game(game_id="porch")
        game_master.submit_move(game_id="porch", player="human", position=1)
        game_master.submit_move(game_id="porch", player="agent", position=4)
        game_master.submit_move(game_id="porch", player="human", position=2)
        game_master.submit_move(game_id="porch", player="agent", position=5)
        won = game_master.submit_move(game_id="porch", player="human", position=3)
        late = game_master.submit_move(game_id="porch", player="agent", position=6)

        assert won["status"] == "won"
        assert won["winner"] == "human"
        assert won["winning_line"] == [1, 2, 3]
        assert late["error"] == "Game porch is already won. Start a new game to play again."

    def test_detects_draw(self):
        import game_master

        game_master.new_game(game_id="porch")
        moves = [
            ("human", 1), ("agent", 2), ("human", 3),
            ("agent", 5), ("human", 4), ("agent", 6),
            ("human", 8), ("agent", 7), ("human", 9),
        ]
        for player, position in moves:
            state = game_master.submit_move(game_id="porch", player=player, position=position)

        assert state["status"] == "draw"
        assert state["winner"] is None

    def test_render_board_uses_numbers_for_empty_squares(self):
        import game_master

        state = game_master.new_game(game_id="porch")
        state = game_master.submit_move(game_id="porch", player="human", position=5)

        assert state["rendered_board"] == "1 | 2 | 3\n--+---+--\n4 | X | 6\n--+---+--\n7 | 8 | 9"


class TestBackgammonLogic:
    def test_backgammon_new_game_uses_standard_setup_and_persists_state(self):
        import game_master

        state = game_master.backgammon_new_game(game_id="sunny-table")

        assert state["game_id"] == "sunny-table"
        assert state["game"] == "backgammon"
        assert state["status"] == "playing"
        assert state["turn"] == "human"
        assert state["bar"] == {"human": 0, "agent": 0}
        assert state["off"] == {"human": 0, "agent": 0}
        assert state["dice"] == []
        assert state["remaining_moves"] == []
        assert state["points"][23] == {"human": 2}
        assert state["points"][12] == {"human": 5}
        assert state["points"][7] == {"human": 3}
        assert state["points"][5] == {"human": 5}
        assert state["points"][0] == {"agent": 2}
        assert state["points"][11] == {"agent": 5}
        assert state["points"][16] == {"agent": 3}
        assert state["points"][18] == {"agent": 5}
        assert game_master.backgammon_load_game("sunny-table") == state

    def test_backgammon_rendered_board_is_readable_for_chat_players(self):
        import game_master

        state = game_master.backgammon_new_game(game_id="sunny-table")

        assert state["rendered_board"] == (
            "Backgammon — Human moves 24→1, Agent moves 1→24\n"
            "+-------------------------------------------------------------+\n"
            "| 13  14  15  16  17  18 | BAR | 19  20  21  22  23  24 |\n"
            "| H5  ·   ·   ·   A3  · |     | A5  ·   ·   ·   ·   H2 |\n"
            "|-------------------------+-----+-------------------------|\n"
            "| A5  ·   ·   ·   H3  · |     | H5  ·   ·   ·   ·   A2 |\n"
            "| 12  11  10  09  08  07 | BAR | 06  05  04  03  02  01 |\n"
            "+-------------------------------------------------------------+\n"
            "Bar: Human 0, Agent 0 | Off: Human 0, Agent 0 | Dice: none | Moves left: none"
        )

    def test_backgammon_roll_sets_dice_and_doubles_expand_to_four_moves(self):
        import game_master

        game_master.backgammon_new_game(game_id="sunny-table")
        rolled = game_master.backgammon_roll(game_id="sunny-table", player="human", die1=3, die2=3)

        assert rolled["error"] is None
        assert rolled["dice"] == [3, 3]
        assert rolled["remaining_moves"] == [3, 3, 3, 3]

    def test_backgammon_move_consumes_die_and_moves_checker_directionally(self):
        import game_master

        game_master.backgammon_new_game(game_id="sunny-table")
        game_master.backgammon_roll(game_id="sunny-table", player="human", die1=3, die2=5)
        moved = game_master.backgammon_move(
            game_id="sunny-table", player="human", from_point=24, to_point=21
        )

        assert moved["error"] is None
        assert moved["points"][23] == {"human": 1}
        assert moved["points"][20] == {"human": 1}
        assert moved["remaining_moves"] == [5]
        assert moved["turn"] == "human"

    def test_backgammon_move_hits_single_opposing_checker(self):
        import game_master

        state = game_master.backgammon_new_game(game_id="sunny-table")
        state["points"] = [{} for _ in range(24)]
        state["points"][7] = {"human": 1}
        state["points"][4] = {"agent": 1}
        game_master.backgammon_save_game(state)
        game_master.backgammon_roll(game_id="sunny-table", player="human", die1=3, die2=4)
        moved = game_master.backgammon_move(
            game_id="sunny-table", player="human", from_point=8, to_point=5
        )

        assert moved["error"] is None
        assert moved["points"][7] == {}
        assert moved["points"][4] == {"human": 1}
        assert moved["bar"] == {"human": 0, "agent": 1}
        assert moved["remaining_moves"] == [4]

    def test_backgammon_move_rejects_blocked_point_wrong_distance_and_wrong_turn(self):
        import game_master

        state = game_master.backgammon_new_game(game_id="sunny-table")
        state["points"] = [{} for _ in range(24)]
        state["points"][7] = {"human": 1}
        state["points"][4] = {"agent": 2}
        game_master.backgammon_save_game(state)
        game_master.backgammon_roll(game_id="sunny-table", player="human", die1=3, die2=4)

        blocked = game_master.backgammon_move(
            game_id="sunny-table", player="human", from_point=8, to_point=5
        )
        wrong_distance = game_master.backgammon_move(
            game_id="sunny-table", player="human", from_point=8, to_point=6
        )
        wrong_turn = game_master.backgammon_move(
            game_id="sunny-table", player="agent", from_point=12, to_point=15
        )

        assert blocked["error"] == "Point 5 is blocked by agent."
        assert wrong_distance["error"] == "Move distance 2 is not available in remaining dice [3, 4]."
        assert wrong_turn["error"] == "It is human's turn, not agent's."


class TestBackgammonBarAndBearOff:
    def test_bar_checker_blocks_moves_and_enters_with_hit(self):
        import game_master

        state = game_master.backgammon_new_game(game_id="sunny-table")
        state["points"] = [{} for _ in range(24)]
        state["points"][7] = {"human": 1}
        state["points"][20] = {"agent": 1}
        state["bar"]["human"] = 1
        game_master.backgammon_save_game(state)
        game_master.backgammon_roll(game_id="sunny-table", player="human", die1=4, die2=2)

        blocked = game_master.backgammon_move(
            game_id="sunny-table", player="human", from_point=8, to_point=4
        )
        assert "must enter" in blocked["error"]

        entered = game_master.backgammon_enter(
            game_id="sunny-table", player="human", to_point=21
        )
        assert entered["error"] is None
        assert entered["bar"] == {"human": 0, "agent": 1}
        assert entered["points"][20] == {"human": 1}
        assert entered["remaining_moves"] == [2]

    def test_enter_rejects_wrong_die_and_blocked_point(self):
        import game_master

        state = game_master.backgammon_new_game(game_id="sunny-table")
        state["points"] = [{} for _ in range(24)]
        state["points"][20] = {"agent": 2}
        state["bar"]["human"] = 1
        game_master.backgammon_save_game(state)
        game_master.backgammon_roll(game_id="sunny-table", player="human", die1=4, die2=2)

        blocked = game_master.backgammon_enter(
            game_id="sunny-table", player="human", to_point=21
        )
        wrong_die = game_master.backgammon_enter(
            game_id="sunny-table", player="human", to_point=19
        )
        assert blocked["error"] == "Point 21 is blocked by agent."
        assert "not in remaining dice" in wrong_die["error"]

    def test_bear_off_requires_all_home_then_wins(self):
        import game_master

        state = game_master.backgammon_new_game(game_id="sunny-table")
        state["points"] = [{} for _ in range(24)]
        state["points"][0] = {"human": 1}
        state["points"][7] = {"human": 1}
        state["off"]["human"] = 13
        game_master.backgammon_save_game(state)
        game_master.backgammon_roll(game_id="sunny-table", player="human", die1=1, die2=2)

        not_home = game_master.backgammon_bear_off(
            game_id="sunny-table", player="human", from_point=1
        )
        assert "every checker is home" in not_home["error"]

        game_master.backgammon_move(
            game_id="sunny-table", player="human", from_point=8, to_point=6
        )
        first_off = game_master.backgammon_bear_off(
            game_id="sunny-table", player="human", from_point=1
        )
        assert first_off["error"] is None
        assert first_off["off"]["human"] == 14
        assert first_off["turn"] == "agent"

        game_master.backgammon_roll(game_id="sunny-table", player="agent", die1=1, die2=2)
        game_master.backgammon_end_turn(game_id="sunny-table", player="agent")
        game_master.backgammon_roll(game_id="sunny-table", player="human", die1=6, die2=3)
        won = game_master.backgammon_bear_off(
            game_id="sunny-table", player="human", from_point=6
        )
        assert won["error"] is None
        assert won["status"] == "won"
        assert won["winner"] == "human"

    def test_bear_off_larger_die_only_with_no_checker_farther_back(self):
        import game_master

        state = game_master.backgammon_new_game(game_id="sunny-table")
        state["points"] = [{} for _ in range(24)]
        state["points"][1] = {"human": 1}
        state["points"][4] = {"human": 1}
        state["off"]["human"] = 13
        game_master.backgammon_save_game(state)
        game_master.backgammon_roll(game_id="sunny-table", player="human", die1=6, die2=6)

        farther_back = game_master.backgammon_bear_off(
            game_id="sunny-table", player="human", from_point=2
        )
        assert "larger die" in farther_back["error"]

        allowed = game_master.backgammon_bear_off(
            game_id="sunny-table", player="human", from_point=5
        )
        assert allowed["error"] is None
        assert allowed["off"]["human"] == 14


class TestConnectFourLogic:
    def test_new_game_and_drop_stacks_to_bottom(self):
        import game_master

        state = game_master.connect4_new_game(game_id="den")
        assert state["game"] == "connect-four"
        assert state["board"] == [""] * 42
        assert state["turn"] == "human"

        dropped = game_master.connect4_drop(game_id="den", player="human", column=4)
        assert dropped["error"] is None
        assert dropped["board"][5 * 7 + 3] == "human"
        assert dropped["turn"] == "agent"

        stacked = game_master.connect4_drop(game_id="den", player="agent", column=4)
        assert stacked["board"][4 * 7 + 3] == "agent"

    def test_rejects_wrong_turn_and_full_column(self):
        import game_master

        game_master.connect4_new_game(game_id="den")
        game_master.connect4_drop(game_id="den", player="human", column=1)
        wrong_turn = game_master.connect4_drop(game_id="den", player="human", column=1)
        assert wrong_turn["error"] == "It is agent's turn, not human's."

        players = ["agent", "human", "agent", "human", "agent"]
        for player in players:
            game_master.connect4_drop(game_id="den", player=player, column=1)
        full = game_master.connect4_drop(game_id="den", player="human", column=1)
        assert full["error"] == "Column 1 is full."

    def test_detects_vertical_win(self):
        import game_master

        game_master.connect4_new_game(game_id="den")
        for _ in range(3):
            game_master.connect4_drop(game_id="den", player="human", column=2)
            game_master.connect4_drop(game_id="den", player="agent", column=5)
        won = game_master.connect4_drop(game_id="den", player="human", column=2)

        assert won["status"] == "won"
        assert won["winner"] == "human"
        assert len(won["winning_cells"]) == 4

        late = game_master.connect4_drop(game_id="den", player="agent", column=5)
        assert late["error"] == "Game den is already won. Start a new game to play again."


class TestCheckersLogic:
    def test_new_game_places_twelve_pieces_each(self):
        import game_master

        state = game_master.checkers_new_game(game_id="hearth")
        assert state["game"] == "checkers"
        assert state["board"].count("human") == 12
        assert state["board"].count("agent") == 12
        assert state["turn"] == "human"

    def test_simple_move_and_wrong_square_rejected(self):
        import game_master

        game_master.checkers_new_game(game_id="hearth")
        moved = game_master.checkers_move(
            game_id="hearth", player="human", from_square=43, to_square=36
        )
        assert moved["error"] is None
        assert moved["board"][35] == "human"
        assert moved["turn"] == "agent"

        bad = game_master.checkers_move(
            game_id="hearth", player="agent", from_square=24, to_square=40
        )
        assert bad["error"] == "Square 24 cannot move to square 40."

    def test_capture_is_mandatory_and_multi_jump_continues(self):
        import game_master

        state = game_master.checkers_new_game(game_id="hearth")
        state["board"] = [""] * 64
        state["board"][42] = "human"       # row 5, col 2 → square 43
        state["board"][33] = "agent"      # row 4, col 1 → square 34
        state["board"][17] = "agent"      # row 2, col 1 → square 18
        state["board"][62] = "human"       # extra human piece far away, square 63
        state["board"][7] = "agent"       # extra agent piece, square 8
        game_master.checkers_save_game(state)

        refused = game_master.checkers_move(
            game_id="hearth", player="human", from_square=63, to_square=54
        )
        assert refused["error"] == "A capture is available; you must jump."

        first_jump = game_master.checkers_move(
            game_id="hearth", player="human", from_square=43, to_square=25
        )
        assert first_jump["error"] is None
        assert first_jump["board"][33] == ""
        assert first_jump["must_continue_from"] == 25
        assert first_jump["turn"] == "human"

        second_jump = game_master.checkers_move(
            game_id="hearth", player="human", from_square=25, to_square=11
        )
        assert second_jump["error"] is None
        assert second_jump["board"][17] == ""
        assert second_jump["must_continue_from"] is None
        assert second_jump["turn"] == "agent"

    def test_crowning_makes_king_and_ends_turn(self):
        import game_master

        state = game_master.checkers_new_game(game_id="hearth")
        state["board"] = [""] * 64
        state["board"][8] = "human"        # row 1, col 0 → square 9
        state["board"][23] = "agent"      # keep agent alive, square 24
        game_master.checkers_save_game(state)

        crowned = game_master.checkers_move(
            game_id="hearth", player="human", from_square=9, to_square=2
        )
        assert crowned["error"] is None
        assert crowned["board"][1] == "human-king"
        assert crowned["turn"] == "agent"

    def test_win_when_opponent_has_no_pieces(self):
        import game_master

        state = game_master.checkers_new_game(game_id="hearth")
        state["board"] = [""] * 64
        state["board"][42] = "human"       # square 43
        state["board"][33] = "agent"      # square 34, human's only capture
        game_master.checkers_save_game(state)

        won = game_master.checkers_move(
            game_id="hearth", player="human", from_square=43, to_square=25
        )
        assert won["status"] == "won"
        assert won["winner"] == "human"


class TestChessLogic:
    def test_new_game_has_twenty_legal_moves_for_red(self):
        import game_master

        state = game_master.chess_new_game(game_id="study")
        assert state["game"] == "chess"
        assert state["turn"] == "human"
        total = sum(len(targets) for targets in state["legal_moves"].values())
        assert total == 20
        assert sorted(state["legal_moves"]["e2"]) == ["e3", "e4"]

    def test_moves_alternate_and_illegal_moves_are_rejected(self):
        import game_master

        game_master.chess_new_game(game_id="study")
        opened = game_master.chess_submit_move(
            game_id="study", player="human", from_square="e2", to_square="e4"
        )
        assert opened["error"] is None
        assert opened["board"][game_master._chess_square_idx("e4")] == "wP"

        wrong_turn = game_master.chess_submit_move(
            game_id="study", player="human", from_square="d2", to_square="d4"
        )
        assert wrong_turn["error"] == "It is agent's turn, not human's."

        illegal = game_master.chess_submit_move(
            game_id="study", player="agent", from_square="e7", to_square="e4"
        )
        assert illegal["error"] == "e7 → e4 is not a legal move."

    def test_fools_mate_is_checkmate_and_recorded(self):
        import game_master

        game_master.chess_new_game(game_id="study")
        for player, source, target in (
            ("human", "f2", "f3"), ("agent", "e7", "e5"),
            ("human", "g2", "g4"),
        ):
            state = game_master.chess_submit_move(
                game_id="study", player=player, from_square=source, to_square=target
            )
            assert state["error"] is None
        mate = game_master.chess_submit_move(
            game_id="study", player="agent", from_square="d8", to_square="h4"
        )
        assert mate["status"] == "won"
        assert mate["winner"] == "agent"
        assert "record_id" in mate
        ledger = game_master.gameroom_records()
        assert ledger["records"][0]["game"] == "chess"
        assert "checkmate" in ledger["records"][0]["detail"]

    def test_kingside_castling_moves_the_rook(self):
        import game_master

        game_master.chess_new_game(game_id="study")
        for player, source, target in (
            ("human", "e2", "e4"), ("agent", "e7", "e5"),
            ("human", "g1", "f3"), ("agent", "b8", "c6"),
            ("human", "f1", "c4"), ("agent", "f8", "c5"),
        ):
            assert game_master.chess_submit_move(
                game_id="study", player=player, from_square=source, to_square=target
            )["error"] is None
        castled = game_master.chess_submit_move(
            game_id="study", player="human", from_square="e1", to_square="g1"
        )
        assert castled["error"] is None
        idx = game_master._chess_square_idx
        assert castled["board"][idx("g1")] == "wK"
        assert castled["board"][idx("f1")] == "wR"
        assert castled["board"][idx("h1")] == ""
        assert castled["castling"]["human"] == {"kingside": False, "queenside": False}

    def test_en_passant_captures_the_passed_pawn(self):
        import game_master

        game_master.chess_new_game(game_id="study")
        for player, source, target in (
            ("human", "e2", "e4"), ("agent", "a7", "a6"),
            ("human", "e4", "e5"),
        ):
            assert game_master.chess_submit_move(
                game_id="study", player=player, from_square=source, to_square=target
            )["error"] is None
        double = game_master.chess_submit_move(
            game_id="study", player="agent", from_square="d7", to_square="d5"
        )
        assert double["en_passant"] == "d6"
        captured = game_master.chess_submit_move(
            game_id="study", player="human", from_square="e5", to_square="d6"
        )
        idx = game_master._chess_square_idx
        assert captured["error"] is None
        assert captured["board"][idx("d6")] == "wP"
        assert captured["board"][idx("d5")] == ""
        assert captured["moves"][-1]["capture"] is True

    def test_promotion_and_stalemate(self):
        import game_master

        state = game_master.chess_new_game(game_id="study")
        idx = game_master._chess_square_idx
        board = [""] * 64
        board[idx("e1")] = "wK"
        board[idx("e8")] = "bK"
        board[idx("a7")] = "wP"
        state["board"] = board
        state["castling"] = {
            "human": {"kingside": False, "queenside": False},
            "agent": {"kingside": False, "queenside": False},
        }
        game_master.chess_save_game(state)
        promoted = game_master.chess_submit_move(
            game_id="study", player="human", from_square="a7", to_square="a8"
        )
        assert promoted["error"] is None
        assert promoted["board"][idx("a8")] == "wQ"
        assert promoted["in_check"] is True

        state = game_master.chess_new_game(game_id="study")
        board = [""] * 64
        board[idx("a8")] = "bK"
        board[idx("b6")] = "wK"
        board[idx("c6")] = "wQ"
        state["board"] = board
        state["castling"] = {
            "human": {"kingside": False, "queenside": False},
            "agent": {"kingside": False, "queenside": False},
        }
        game_master.chess_save_game(state)
        stalemate = game_master.chess_submit_move(
            game_id="study", player="human", from_square="c6", to_square="c7"
        )
        assert stalemate["status"] == "draw"
        assert stalemate["draw_reason"] == "stalemate"


class TestBattleshipLogic:
    def test_new_game_places_valid_hidden_fleets(self):
        import game_master

        state = game_master.battleship_new_game(game_id="harbor")
        for player in ("human", "agent"):
            fleet = state["fleets"][player]
            assert sorted(len(ship["cells"]) for ship in fleet) == [2, 3, 3, 4, 5]
            cells = [cell for ship in fleet for cell in ship["cells"]]
            assert len(cells) == len(set(cells)) == 17
            assert all(0 <= cell < 100 for cell in cells)

    def test_views_are_redacted_per_player(self):
        import game_master

        game_master.battleship_new_game(game_id="harbor")
        view = game_master.battleship_get_view(game_id="harbor", player="human")
        assert view["viewer"] == "human"
        assert "fleets" not in view
        assert view["your_board"].count("ship") == 17
        assert all(cell == "" for cell in view["target_board"])
        assert view["enemy_ships_afloat"] == 5

    def test_fire_hit_miss_turns_and_double_shot(self):
        import game_master

        state = game_master.battleship_new_game(game_id="harbor")
        jack_cells = {cell for ship in state["fleets"]["agent"] for cell in ship["cells"]}
        empty = next(i for i in range(100) if i not in jack_cells)
        ship_cell = min(jack_cells)
        name = game_master._battleship_coord_name

        miss = game_master.battleship_fire(game_id="harbor", player="human", coordinate=name(empty))
        assert miss["last_move"]["result"] == "miss"
        assert miss["turn"] == "agent"

        wrong = game_master.battleship_fire(game_id="harbor", player="human", coordinate="A1")
        assert wrong["error"] == "It is agent's turn, not human's."
        assert "'human' seat" not in wrong["error"]

        game_master.battleship_fire(game_id="harbor", player="agent", coordinate="J10")
        hit = game_master.battleship_fire(game_id="harbor", player="human", coordinate=name(ship_cell))
        assert hit["last_move"]["result"] in ("hit", "sunk")

        game_master.battleship_fire(game_id="harbor", player="agent", coordinate="J9")
        repeat = game_master.battleship_fire(game_id="harbor", player="human", coordinate=name(ship_cell))
        assert "already fired" in repeat["error"]

    def test_agent_seat_refusal_explains_the_human_seat(self):
        import game_master

        game_master.battleship_new_game(game_id="harbor")
        stuck = game_master.battleship_fire(game_id="harbor", player="agent", coordinate="A1")
        assert stuck["error"].startswith("It is human's turn, not agent's.")
        assert "player='human'" in stuck["error"]
        assert stuck["last_move"] is None

        opened = game_master.battleship_fire(game_id="harbor", player="human", coordinate="A1")
        assert opened["error"] is None
        assert opened["turn"] == "agent"

    def test_view_reports_both_sides_shot_counts(self):
        import game_master

        game_master.battleship_new_game(game_id="harbor")
        opening = game_master.battleship_get_view(game_id="harbor", player="human")
        assert opening["shots_fired"] == 0
        assert opening["opponent_shots_fired"] == 0

        game_master.battleship_fire(game_id="harbor", player="human", coordinate="A1")
        game_master.battleship_fire(game_id="harbor", player="agent", coordinate="J10")

        human = game_master.battleship_get_view(game_id="harbor", player="human")
        agent = game_master.battleship_get_view(game_id="harbor", player="agent")
        assert human["shots_fired"] == human["opponent_shots_fired"] == 1
        assert agent["shots_fired"] == agent["opponent_shots_fired"] == 1
        assert "Table harbor" in human["rendered_board"]
        # it must stay a count, never a position
        assert "fleets" not in human and "fleets" not in agent

    def test_sinking_the_last_ship_wins_and_is_recorded(self):
        import game_master

        state = game_master.battleship_new_game(game_id="harbor")
        destroyer = next(s for s in state["fleets"]["agent"] if len(s["cells"]) == 2)
        for ship in state["fleets"]["agent"]:
            if ship is not destroyer:
                ship["hits"] = list(ship["cells"])
        game_master.battleship_save_game(state)
        name = game_master._battleship_coord_name

        first = game_master.battleship_fire(
            game_id="harbor", player="human", coordinate=name(destroyer["cells"][0])
        )
        assert first["last_move"]["result"] == "hit"
        game_master.battleship_fire(game_id="harbor", player="agent", coordinate="A1")
        won = game_master.battleship_fire(
            game_id="harbor", player="human", coordinate=name(destroyer["cells"][1])
        )
        assert won["status"] == "won"
        assert won["winner"] == "human"
        assert won["last_move"]["ship"] == "Destroyer"
        assert "record_id" in won

    def test_shuffle_only_before_battle_starts(self):
        import game_master

        game_master.battleship_new_game(game_id="harbor")
        shuffled = game_master.battleship_shuffle(game_id="harbor", player="human")
        assert shuffled["error"] is None
        game_master.battleship_fire(game_id="harbor", player="human", coordinate="A1")
        late = game_master.battleship_shuffle(game_id="harbor", player="agent")
        assert late["error"] == "The battle has begun — fleets are committed."


class TestHouseLedger:
    def test_finished_games_are_recorded_and_annotatable(self):
        import game_master

        game_master.new_game(game_id="porch")
        game_master.submit_move(game_id="porch", player="human", position=1)
        game_master.submit_move(game_id="porch", player="agent", position=4)
        game_master.submit_move(game_id="porch", player="human", position=2)
        game_master.submit_move(game_id="porch", player="agent", position=5)
        won = game_master.submit_move(game_id="porch", player="human", position=3)
        assert "record_id" in won

        ledger = game_master.gameroom_records()
        assert ledger["stats"]["score"]["human"] == 1
        assert ledger["stats"]["streak"] == {"player": "human", "count": 1}
        assert ledger["stats"]["per_game"]["tic-tac-toe"]["human"] == 1
        assert ledger["records"][0]["id"] == won["record_id"]

        annotated = game_master.gameroom_annotate(
            record_id=won["record_id"],
            title="The Porch Massacre",
            note="Three in a row before the coffee cooled.",
        )
        assert annotated["state"] == "live"
        again = game_master.gameroom_records()
        assert again["records"][0]["title"] == "The Porch Massacre"

        missing = game_master.gameroom_annotate(record_id="nope")
        assert missing["state"] == "error"


def test_tool_defaults_land_at_the_rooms_tables(fake_server):
    """Nobody should have to name a table: the tool defaults are the room's."""
    import game_master

    battle = json.loads(asyncio.run(fake_server._tool_manager.call_tool("battleship_new")))
    assert battle["game_id"] == game_master.TABLE_BATTLESHIP
    noughts = json.loads(asyncio.run(fake_server._tool_manager.call_tool("game_new")))
    assert noughts["game_id"] == game_master.TABLE_TICTACTOE


def test_starting_a_game_does_not_throw_away_one_in_progress(fake_server):
    import game_master

    call = fake_server._tool_manager.call_tool
    asyncio.run(call("battleship_new"))
    fired = json.loads(asyncio.run(call("battleship_fire_shot", {"player": "human", "coordinate": "A1"})))
    assert fired["opponent_shots_fired"] == 0
    assert fired["shots_fired"] == 1

    resumed = json.loads(asyncio.run(call("battleship_new")))
    assert resumed["error"] == game_master.RESUME_NOTE
    assert resumed["opponent_shots_fired"] == 1  # the agent's view of that shot

    dealt_again = json.loads(asyncio.run(call("battleship_new", {"reset": True})))
    assert dealt_again["error"] is None
    assert dealt_again["opponent_shots_fired"] == 0

    # and the same protection on a game with an ordinary shared board
    asyncio.run(call("game_new"))
    asyncio.run(call("game_submit_move", {"player": "human", "position": 5}))
    guarded = json.loads(asyncio.run(call("game_new")))
    assert guarded["error"] == game_master.RESUME_NOTE
    assert guarded["board"][4] == "X"
    assert json.loads(asyncio.run(call("game_new", {"reset": True})))["board"][4] == ""

    # an untouched table is nobody's game yet — re-dealing it is harmless
    fresh = json.loads(asyncio.run(call("game_new")))
    assert fresh["error"] is None


def test_mcp_tools_expose_playable_games(fake_server):
    tools = {tool.name for tool in fake_server._tool_manager.list_tools()}
    assert tools == {
        "game_new", "game_get_state", "game_submit_move",
        "backgammon_new", "backgammon_get_state", "backgammon_roll",
        "backgammon_move", "backgammon_enter", "backgammon_bear_off",
        "backgammon_end_turn",
        "connect4_new", "connect4_get_state", "connect4_drop",
        "checkers_new", "checkers_get_state", "checkers_submit_move",
        "chess_new", "chess_get_state", "chess_move",
        "battleship_new", "battleship_get_state", "battleship_fire_shot",
        "battleship_shuffle_fleet",
        "gameroom_ledger", "gameroom_annotate_match",
    }

    created = asyncio.run(fake_server._tool_manager.call_tool("game_new", {"game_id": "porch"}))
    moved = asyncio.run(fake_server._tool_manager.call_tool(
        "game_submit_move", {"game_id": "porch", "player": "human", "position": 5}
    ))
    fetched = asyncio.run(fake_server._tool_manager.call_tool("game_get_state", {"game_id": "porch"}))
    backgammon = asyncio.run(fake_server._tool_manager.call_tool(
        "backgammon_new", {"game_id": "sunny-table"}
    ))

    created_data = json.loads(created)
    moved_data = json.loads(moved)
    fetched_data = json.loads(fetched)
    backgammon_data = json.loads(backgammon)

    assert created_data["status"] == "playing"
    assert moved_data["board"][4] == "X"
    assert fetched_data == moved_data
    assert backgammon_data["game"] == "backgammon"
    assert backgammon_data["points"][23] == {"human": 2}
