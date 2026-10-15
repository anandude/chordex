import pytest


@pytest.fixture(autouse=True)
def _no_local_ct2_models(tmp_path, monkeypatch):
    """Routing prefers local CTranslate2 conversions (models/ct2/); tests
    must not depend on what happens to be converted on this machine."""
    monkeypatch.setenv("LYRICS_CT2_DIR", str(tmp_path / "ct2"))
