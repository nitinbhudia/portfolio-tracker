import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# These tests were written for Fibonacci AI's own demo holdings; in Portfolio Tracker the default is the tracker's.
import research.api.routes as _routes  # noqa: E402

_routes.DEFAULTS["holdings_source"] = "synthetic"


@pytest.fixture(scope="session")
def client(tmp_path_factory):
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    from research.data.seed import import_holdings, seed_universe
    from research.db.session import Base, get_db, make_engine
    from research.main import app
    from research.services.analysis import persist_latest_all

    db_path = tmp_path_factory.mktemp("db") / "test.db"
    engine = make_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    with TestSession() as db:
        seed_universe(db)
        import_holdings(db)
        persist_latest_all(db)
        db.commit()

    def _get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_db
    c = TestClient(app, raise_server_exceptions=False)
    c.Session = TestSession
    yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def aapl():
    from datetime import date

    import numpy as np

    from research.data.synthetic import generate_ohlcv

    rows = generate_ohlcv("AAPL", "XNAS", 180.0, 0.28, date(2025, 12, 31), 600)
    return {k: np.array([r[k] for r in rows], dtype=float) for k in ("open", "high", "low", "close", "volume")}


ECB_CSV = (Path(__file__).parent / "fixtures" / "ecb_sample.csv").read_text()


def fake_ecb_client(csv_text: str = ECB_CSV, status: int = 200):
    """An EcbClient whose HTTP calls are answered from a recorded ECB response (no network)."""
    import httpx

    from research.market_data.ecb import EcbClient

    def handle(req):
        return httpx.Response(status, text=csv_text if status == 200 else "error")
    return EcbClient(httpx.Client(transport=httpx.MockTransport(handle)))


@pytest.fixture(autouse=True)
def _no_live_ecb(monkeypatch):
    """Tests never call the real ECB service."""
    from research.market_data import fx
    monkeypatch.setattr(fx, "EcbClient", lambda *a, **k: fake_ecb_client())
