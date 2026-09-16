import datetime as dt

import pytest

import surebet.scanner as scanner_module
from surebet.collectors.base import Collector
from surebet.models import Event, MarketFamily, MarketKey, OddQuote, Period, SettlementRules


class FakeArbCollector(Collector):
    name = "fake"

    async def fetch(self):
        market = MarketKey(
            sport_key="soccer_spain_la_liga", event_id="fake1",
            family=MarketFamily.MONEYLINE_2WAY, period=Period.MATCH,
            rules=SettlementRules.STANDARD,
        )
        event = Event(
            event_id="fake1", sport_key="soccer_spain_la_liga", sport_group="soccer",
            league="LaLiga", home="Real Madrid", away="Elche",
            commence_time=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2),
        )
        quotes = [
            OddQuote(bookmaker="Winamax", market=market, selection="home", price_decimal=2.10),
            OddQuote(bookmaker="Bet365", market=market, selection="away", price_decimal=2.10),
        ]
        return [event], quotes


@pytest.mark.asyncio
async def test_scanner_does_not_resend_same_opportunity_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner_module.settings, "sqlite_path", str(tmp_path / "scan_test.db"))

    sent_messages = []

    async def fake_send(text: str) -> bool:
        sent_messages.append(text)
        return True

    monkeypatch.setattr(scanner_module, "send_telegram_message", fake_send)

    summary1 = await scanner_module.run_scan_once([FakeArbCollector()])
    summary2 = await scanner_module.run_scan_once([FakeArbCollector()])

    assert len(summary1) == 1 and summary1[0]["verdict"] == "VALID_ARB"
    assert len(summary2) == 1 and summary2[0]["verdict"] == "VALID_ARB"
    assert summary1[0]["already_alerted"] is False
    assert summary2[0]["already_alerted"] is True

    # La misma oportunidad (mismo evento+mercado) detectada dos pasadas
    # seguidas solo debe generar UN mensaje de Telegram, no dos.
    assert len(sent_messages) == 1
