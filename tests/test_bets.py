import pytest
from fastapi.testclient import TestClient

from surebet.storage.db import (
    bets_summary,
    get_connection,
    init_db,
    list_placed_bets,
    save_placed_bet,
    settle_placed_bet,
)


def test_save_and_list_placed_bet_recomputes_total_staked(tmp_path):
    db_path = str(tmp_path / "t.db")
    init_db(db_path)
    with get_connection(db_path) as conn:
        legs = [
            {"bookmaker": "bet365", "selection": "home", "odds": 2.10, "stake": 50.0},
            {"bookmaker": "pinnacle", "selection": "away", "odds": 4.20, "stake": 25.0},
        ]
        bet_id = save_placed_bet(
            conn, legs=legs, home="Real Madrid", away="Elche", market="three_way",
        )
        conn.commit()

        bets = list_placed_bets(conn)
        assert len(bets) == 1
        assert bets[0]["id"] == bet_id
        assert bets[0]["status"] == "pending"
        assert bets[0]["total_staked"] == 75.0  # recalculado a partir de las piernas, no confiado del cliente
        assert bets[0]["legs"] == legs


def test_settle_placed_bet_computes_profit(tmp_path):
    db_path = str(tmp_path / "t.db")
    init_db(db_path)
    with get_connection(db_path) as conn:
        legs = [
            {"bookmaker": "bet365", "selection": "home", "odds": 2.10, "stake": 50.0},
            {"bookmaker": "pinnacle", "selection": "away", "odds": 4.20, "stake": 25.0},
        ]
        bet_id = save_placed_bet(conn, legs=legs, home="A", away="B", market="three_way")
        conn.commit()

        updated = settle_placed_bet(conn, bet_id, total_returned=105.0)
        conn.commit()

        assert updated["status"] == "settled"
        assert updated["total_returned"] == 105.0
        assert updated["profit"] == pytest.approx(30.0)  # 105 - 75 apostado


def test_settle_unknown_bet_raises(tmp_path):
    db_path = str(tmp_path / "t.db")
    init_db(db_path)
    with get_connection(db_path) as conn:
        with pytest.raises(ValueError):
            settle_placed_bet(conn, 999, total_returned=10.0)


def test_bets_summary_only_counts_settled_for_profit(tmp_path):
    db_path = str(tmp_path / "t.db")
    init_db(db_path)
    with get_connection(db_path) as conn:
        legs = [
            {"bookmaker": "bet365", "selection": "home", "odds": 2.0, "stake": 50.0},
            {"bookmaker": "pinnacle", "selection": "away", "odds": 2.0, "stake": 50.0},
        ]
        pending_id = save_placed_bet(conn, legs=legs, home="A", away="B", market="moneyline_2way")
        settled_id = save_placed_bet(conn, legs=legs, home="C", away="D", market="moneyline_2way")
        settle_placed_bet(conn, settled_id, total_returned=110.0)
        conn.commit()

        summary = bets_summary(conn)
        assert summary["total_bets"] == 2
        assert summary["pending"] == 1
        assert summary["settled"] == 1
        assert summary["total_staked_settled"] == 100.0
        assert summary["total_profit_settled"] == pytest.approx(10.0)
        assert summary["roi_pct_settled"] == pytest.approx(10.0)


def test_bets_api_end_to_end(tmp_path, monkeypatch):
    import surebet.scanner as scanner_module
    from surebet.api import main as api_main

    monkeypatch.setattr(scanner_module.settings, "sqlite_path", str(tmp_path / "api_bets.db"))

    payload = {
        "home": "Real Madrid", "away": "Elche", "market": "three_way",
        "legs": [
            {"bookmaker": "bet365", "selection": "home", "odds": 2.10, "stake": 50.0},
            {"bookmaker": "pinnacle", "selection": "draw", "odds": 4.20, "stake": 15.0},
            {"bookmaker": "pinnacle", "selection": "away", "odds": 4.20, "stake": 15.0},
        ],
    }
    with TestClient(api_main.app) as client:
        create_resp = client.post("/api/bets", json=payload)
        assert create_resp.status_code == 200
        bet_id = create_resp.json()["id"]

        list_resp = client.get("/api/bets")
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1
        assert list_resp.json()[0]["total_staked"] == 80.0

        settle_resp = client.post(f"/api/bets/{bet_id}/settle", json={"total_returned": 105.0})
        assert settle_resp.status_code == 200
        assert settle_resp.json()["profit"] == pytest.approx(25.0)

        summary_resp = client.get("/api/bets/summary")
        assert summary_resp.json()["settled"] == 1
        assert summary_resp.json()["total_profit_settled"] == pytest.approx(25.0)
