import pytest


@pytest.fixture(autouse=True)
def ocr_cache_dir(tmp_path, monkeypatch):
    """Every test gets its own empty OCR cache: none reads or fills the user's real one."""
    monkeypatch.setenv("HUKUM_RAPIH_OCR_CACHE", str(tmp_path / "ocr-cache"))


@pytest.fixture(autouse=True)
def no_archive_mappings(monkeypatch):
    """No test reads the archive's mappings from GitHub: BPK downloads go to the test's fake
    session unless a test lists copies itself."""
    from hukum_rapih.sources import dharmasastra

    monkeypatch.setattr(dharmasastra, "copies", dict)
