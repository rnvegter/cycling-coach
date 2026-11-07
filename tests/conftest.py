"""Fixtures voor alle tests."""
import pytest  # noqa: F401
from helpers import *  # noqa: F403


@pytest.fixture(autouse=True)
def tmpdata(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DATA", tmp_path)



@pytest.fixture
def web_cfg(monkeypatch):
    from fietscoach import web
    cfg = dict(VOORBEELD, uitzonderingen={}, afwezig=[])
    monkeypatch.setattr(service, "laad_config", lambda *a: cfg)
    monkeypatch.setattr(service, "bewaar_instellingen", lambda c: cfg.update(c))
    monkeypatch.setattr(web, "vandaag", lambda: date(2026, 11, 10))
    return cfg

