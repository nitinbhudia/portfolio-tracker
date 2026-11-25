"""Break-even calculator storage (the maths is tested in frontend/lib/breakeven.test.ts)."""
from .test_api import client  # noqa: F401  (fixture re-used)


def test_save_and_load(client):  # noqa: F811
    assert client.get("/api/breakeven").json() == {"calcs": []}
    calc = {"id": "a", "name": "Micron", "currency": "usd", "lots": [{"shares": 6, "price": 883}], "price": 633.55, "steps": [1, 3, 17]}
    out = client.put("/api/breakeven", json={"calcs": [calc]}).json()["calcs"][0]
    assert out["currency"] == "USD" and out["lots"] == [{"shares": 6.0, "price": 883.0, "fee": None, "date": None}] and out["steps"] == [1, 3, 17]
    assert client.get("/api/breakeven").json()["calcs"][0]["name"] == "Micron"
    bad = [{"lots": [{"shares": -1, "price": 5}]}, {"lots": [{"shares": "x", "price": 5}]}, {"steps": [0]}]
    for b in bad:
        assert client.put("/api/breakeven", json={"calcs": [b]}).status_code == 400
    assert client.put("/api/breakeven", json={"calcs": [{}] * 51}).status_code == 400
