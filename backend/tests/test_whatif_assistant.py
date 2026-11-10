"""What-if engine, sectors and the assistant loop (scripted stand-in for Claude; no network).

Made-up book (tests/test_engine.py::book) after FIFO: Alpha Corp 5 shares left from the 2024-02-01 purchase at 110
(sheet price 125, USD); Epsilon 2 shares bought 2024-05-01 at 30 (price 33). Hand-checked numbers below.
"""
import json
from types import SimpleNamespace as NS

import pytest

from app.services import assistant as AS
from app.services import whatif as WS

from .test_api import client, upload  # noqa: F401  (fixture re-used)


def pools(c):
    return {h["stock"]: h for h in c.get("/api/whatif").json()["holdings"]}


# ---------------------------------------------------------------- what-if

def test_sell_one_stock_by_hand(client):  # noqa: F811
    upload(client)
    a = pools(client)["Alpha Corp"]
    r = client.post("/api/whatif/sell", json={"items": [{"pool": a["pool"], "shares": 2}]}).json()
    (s,) = r["sales"]
    assert s["proceeds_usd"] == pytest.approx(250) and s["cost_usd"] == pytest.approx(220) and s["gain_usd"] == pytest.approx(30)
    assert s["lots"][0]["bought"] == "2024-02-01" and s["remaining_shares"] == 3
    assert s["held_over_1y_gain_usd"] == pytest.approx(30)  # bought in 2024, valued today
    assert r["year"]["realised_after_usd"] == pytest.approx(r["year"]["realised_so_far_usd"] + 30)
    pct = client.post("/api/whatif/sell", json={"items": [{"pool": a["pool"], "percent": 40}]}).json()
    assert pct["sales"][0]["shares"] == pytest.approx(2)
    fee = client.post("/api/whatif/sell", json={"items": [{"pool": a["pool"], "shares": 2}], "fee_per_sale": 5}).json()
    assert fee["totals"]["gain_usd"] == pytest.approx(25)


def test_sell_everything_sector_and_errors(client):  # noqa: F811
    upload(client)
    allr = client.post("/api/whatif/sell", json={"everything": True}).json()
    assert allr["totals"]["gain_usd"] == pytest.approx(5 * 15 + 2 * 3)  # Alpha +75, Epsilon +6
    assert allr["portfolio"]["value_after_usd"] == pytest.approx(0)
    assert client.post("/api/whatif/sell", json={"sector": "Energy"}).status_code == 400  # no confirmed sectors yet
    a = pools(client)["Alpha Corp"]
    client.put(f"/api/sectors/{a['pool'].split('|')[0]}", json={"sector": "Financials"})
    sec = client.post("/api/whatif/sell", json={"sector": "Financials", "percent": 20}).json()
    assert [s["stock"] for s in sec["sales"]] == ["Alpha Corp"] and sec["sales"][0]["shares"] == pytest.approx(1)
    for bad, msg in [({"items": [{"pool": a["pool"], "shares": 9}]}, "you hold 5"), ({"items": [{"pool": "nope|USD"}]}, "isn't one"),
                     ({"everything": True, "percent": 0}, "percent"), ({}, "Choose at least one")]:
        r = client.post("/api/whatif/sell", json=bad)
        assert r.status_code == 400 and msg in r.json()["message"], bad


def test_rebalance_by_stock_and_sector(client):  # noqa: F811
    upload(client)
    p = pools(client)
    a, e = p["Alpha Corp"], p["Epsilon"]
    total = 5 * 125 + 2 * 33  # 691
    r = client.post("/api/whatif/rebalance", json={"by": "stock", "targets": {a["pool"]: 50}}).json()
    (t,) = r["trades"]  # Alpha 625 -> 345.5: sell floor(279.5/125) = 2 shares
    assert t["action"] == "sell" and t["shares"] == 2 and r["sale"]["totals"]["gain_usd"] == pytest.approx(30)
    assert r["cash_usd"] == pytest.approx(250) and r["total_usd"] == pytest.approx(total)
    up = client.post("/api/whatif/rebalance", json={"by": "stock", "targets": {e["pool"]: 20}}).json()
    (b,) = up["trades"]  # Epsilon 66 -> 138.2: buy floor(72.2/33) = 2
    assert b["action"] == "buy" and b["shares"] == 2 and up["cash_usd"] == pytest.approx(-66) and up["sale"] is None
    client.put(f"/api/sectors/{a['pool'].split('|')[0]}", json={"sector": "Financials"})
    s = client.post("/api/whatif/rebalance", json={"by": "sector", "targets": {"Financials": 0}}).json()
    assert s["trades"][0]["shares"] == 5 and s["sale"]["totals"]["gain_usd"] == pytest.approx(75)
    assert client.post("/api/whatif/rebalance", json={"by": "sector", "targets": {"Mining": 10}}).status_code == 400
    assert client.post("/api/whatif/rebalance", json={"by": "stock", "targets": {a["pool"]: 150}}).status_code == 400
    assert client.post("/api/whatif/rebalance", json={"by": "colour", "targets": {}}).status_code == 400


# ---------------------------------------------------------------- sectors

def fake_message(content, stop="end_turn"):
    def mk(b):
        return NS(**b, to_dict=lambda b=b: dict(b))
    return NS(stop_reason=stop, content=[mk(b) for b in content])


class FakeClient:
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.calls.append(json.loads(json.dumps(kw, default=str)))
        return self.script.pop(0)


def test_sectors_suggest_confirm_and_set(client, monkeypatch):  # noqa: F811
    upload(client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    st = client.get("/api/sectors").json()
    open_names = [x["stock"] for x in st["stocks"] if x["open"]]
    fc = FakeClient([fake_message([{"type": "text", "text": json.dumps(
        {"items": [{"id": 0, "sector": "Financials"}, {"id": 1, "sector": "Industrials"}, {"id": 7, "sector": "Energy"}]})}])])
    monkeypatch.setattr(WS, "make_client", lambda: fc)
    r = client.post("/api/sectors/suggest").json()
    assert r["suggested"] == 2 and r["counts"]["suggested_unconfirmed"] == 2  # id 7 doesn't exist: ignored
    call = fc.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["fallbacks"] == "default"
    assert call["output_config"]["format"]["type"] == "json_schema" and all(n in call["messages"][0]["content"] for n in open_names)
    assert client.post("/api/whatif/sell", json={"sector": "Financials"}).status_code == 400  # unconfirmed: not used yet
    assert client.post("/api/sectors/confirm-all").json()["counts"]["open_confirmed"] == 2
    assert client.put("/api/sectors/x", json={"sector": "Bananas"}).status_code == 400


def test_sectors_need_a_key(client, monkeypatch):  # noqa: F811
    upload(client)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert client.get("/api/assistant/status").json()["available"] is False
    r = client.post("/api/assistant/ask", json={"question": "hi"})
    assert r.status_code == 400 and "ANTHROPIC_API_KEY" in r.json()["message"]


# ---------------------------------------------------------------- assistant loop

def test_assistant_answers_with_tool_results_and_keeps_history(client, monkeypatch):  # noqa: F811
    upload(client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    a = pools(client)["Alpha Corp"]
    script = [
        fake_message([{"type": "thinking", "thinking": "", "signature": "sig1"},
                      {"type": "tool_use", "id": "t1", "name": "find_positions", "input": {"query": "alpha"}}], "tool_use"),
        fake_message([{"type": "tool_use", "id": "t2", "name": "simulate_sale",
                       "input": {"items": [{"pool": a["pool"], "shares": None, "percent": None}], "sector": None,
                                 "everything": False, "percent": None}}], "tool_use"),
        fake_message([{"type": "text", "text": "Selling all 5 Alpha Corp shares now would realise a gain of $75 (before tax)."}]),
    ]
    fc = FakeClient(script)
    monkeypatch.setattr(WS, "make_client", lambda: fc)
    r = client.post("/api/assistant/ask", json={"question": "If I sell all my Alpha now, what's the P&L?"}).json()
    last = r["display"][-1]
    assert "$75" in last["text"] and [c["tool"] for c in last["calls"]] == ["find_positions", "simulate_sale"]
    assert last["calls"][1]["result"]["totals"]["gain_usd"] == 75 and not last["calls"][1]["error"]
    assert last["calls"][0]["result"]["matches"][0]["pool"] == a["pool"]
    first = fc.calls[0]
    assert first["tools"][2]["strict"] is True and "tool_choice" not in first and first["system"][0]["cache_control"]
    # history is append-only and the thinking block is passed back unchanged
    third = fc.calls[2]["messages"]
    assert third[1]["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig1"}
    assert third[2]["content"][0]["tool_use_id"] == "t1"

    fc2 = FakeClient([fake_message([{"type": "text", "text": "You asked about Alpha Corp."}])])
    monkeypatch.setattr(WS, "make_client", lambda: fc2)
    r2 = client.post("/api/assistant/ask", json={"question": "What did I ask?", "chat_id": r["chat_id"]}).json()
    assert len(r2["display"]) == 4 and fc2.calls[0]["messages"][:len(third)] == third[:len(third)]
    assert client.get(f"/api/assistant/chats/{r['chat_id']}").json()["display"] == r2["display"]


def test_assistant_tool_errors_refusals_and_bad_input(client, monkeypatch):  # noqa: F811
    upload(client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    fc = FakeClient([
        fake_message([{"type": "tool_use", "id": "t1", "name": "simulate_rebalance",
                       "input": {"by": "sector", "targets": [{"key": "Mining", "percent": 10}]}}], "tool_use"),
        fake_message([], "refusal"),
    ])
    monkeypatch.setattr(WS, "make_client", lambda: fc)
    r = client.post("/api/assistant/ask", json={"question": "rebalance mining to 10%"}).json()
    last = r["display"][-1]
    assert last["calls"][0]["error"] and "Not an open position" in last["calls"][0]["result"]["error"]
    assert fc.calls[1]["messages"][2]["content"][0]["is_error"] is True
    assert "declined" in last["text"]
    assert client.post("/api/assistant/ask", json={"question": "  "}).status_code == 400
    assert client.post("/api/assistant/ask", json={"question": "x", "chat_id": 999}).status_code == 404
    assert AS.run_tool(None, "drop_tables", {})[1] is True


def test_assistant_maps_api_errors(client, monkeypatch):  # noqa: F811
    import anthropic
    import httpx2
    upload(client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "bad")

    class Boom:
        beta = NS(messages=NS(create=lambda **kw: (_ for _ in ()).throw(anthropic.AuthenticationError(
            "invalid x-api-key", response=httpx2.Response(401, request=httpx2.Request("POST", "https://api.anthropic.com")), body=None))))
    monkeypatch.setattr(WS, "make_client", lambda: Boom())
    r = client.post("/api/assistant/ask", json={"question": "hi"})
    assert r.status_code == 400 and "key was rejected" in r.json()["message"]


def test_assistant_unexpected_client_error_is_a_message(client, monkeypatch):  # noqa: F811
    upload(client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    def broken(**kw):
        raise RuntimeError("socket closed")
    monkeypatch.setattr(WS, "make_client", lambda: NS(beta=NS(messages=NS(create=broken))))
    r = client.post("/api/assistant/ask", json={"question": "hi"})
    assert r.status_code == 400 and "unexpected problem (RuntimeError)" in r.json()["message"]


# ---------------------------------------------------------------- average down

def test_average_down_by_hand(client):  # noqa: F811
    upload(client)
    a = pools(client)["Alpha Corp"]  # 5 shares, FIFO cost 110 each (550), price 125
    r = client.post("/api/whatif/average-down", json={"pool": a["pool"], "buy_price": 100, "shares": 5}).json()
    assert r["now"]["break_even"] == pytest.approx(110) and not r["now"]["in_loss"]
    p = r["plan"]  # 10 shares, cost 1050 -> break-even 105
    assert p["break_even"] == pytest.approx(105) and p["money_usd"] == pytest.approx(500)
    assert p["rise_needed_from_buy_pct"] == pytest.approx(5) and p["if_falls_further_usd"] == pytest.approx(10 * 80 - 1050)
    assert p["if_falls_further_without_usd"] == pytest.approx(5 * 80 - 550)
    # FIFO: selling 5 at 105 takes the old 110 lot -> -25
    assert p["sell_added_at_break_even"]["gain_usd"] == pytest.approx(-25)
    t = client.post("/api/whatif/average-down", json={"pool": a["pool"], "buy_price": 100, "target_break_even": 104}).json()
    assert t["plan"]["shares_added"] == 8  # 5*(110-104)/(104-100) = 7.5 -> 8 whole shares
    m = client.post("/api/whatif/average-down", json={"pool": a["pool"], "buy_price": 100, "amount_usd": 350, "fee": 10}).json()
    assert m["plan"]["shares_added"] == 3 and m["plan"]["money_usd"] == pytest.approx(310)
    std = client.post("/api/whatif/average-down", json={"pool": a["pool"]}).json()
    assert std["plan"] is None and [row["drop_pct"] for row in std["table"]] == [0, 10, 20, 30]
    assert std["table"][0]["plans"][1]["shares_added"] == 5 and std["table"][0]["buy_price"] == pytest.approx(125)
    for bad, msg in [({"target_break_even": 120, "buy_price": 100}, "below it"), ({"target_break_even": 95, "buy_price": 100}, "above the buy price"),
                     ({"shares": 1, "amount_usd": 10}, "not more than one"), ({"buy_price": 0}, "more than 0"), ({"amount_usd": 50, "buy_price": 100}, "one whole share")]:
        res = client.post("/api/whatif/average-down", json={"pool": a["pool"], **bad})
        assert res.status_code == 400 and msg in res.json()["message"], bad


def test_assistant_average_down_tool(client, monkeypatch):  # noqa: F811
    upload(client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    a = pools(client)["Alpha Corp"]
    fc = FakeClient([
        fake_message([{"type": "tool_use", "id": "t1", "name": "simulate_average_down",
                       "input": {"pool": a["pool"], "buy_price": 100, "shares": 5, "amount_usd": None, "target_break_even": None}}], "tool_use"),
        fake_message([{"type": "text", "text": "Buying 5 more at 100 lowers your break-even to 105."}]),
    ])
    monkeypatch.setattr(WS, "make_client", lambda: fc)
    last = client.post("/api/assistant/ask", json={"question": "average down alpha"}).json()["display"][-1]
    assert not last["calls"][0]["error"] and last["calls"][0]["result"]["plan"]["break_even"] == 105
    assert any(t["name"] == "simulate_average_down" for t in fc.calls[0]["tools"])
