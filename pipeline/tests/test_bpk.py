import hashlib
from pathlib import Path

import pytest
from recfactory import make_record, make_version

from hukum_rapih.sources import peraturan_bpk as bpk
from hukum_rapih.sources.dharmasastra import copies as read_copies   # before conftest replaces it

FIX = Path(__file__).parent / "fixtures" / "bpk"


def page(name: str) -> str:
    return (FIX / name).read_text()


def test_listing():
    items = bpk.parse_listing(page("search_uu_p1.html"))
    assert items[0] == bpk.Listing("/Details/350096/uu-no-5-tahun-2026", 350096)
    assert len(items) == 10 and len({i.bpk_id for i in items}) == 10   # 10 results a page
    assert bpk.last_page(page("search_uu_p1.html")) == 193           # 1,929 UU


@pytest.mark.parametrize("cite, work", [
    ("UU No. 2 Tahun 2025", "uu_2_2025"),
    ("PERPU No. 2 Tahun 2022", "perppu_2_2022"),
    ("PP No. 96 Tahun 2021", "pp_96_2021"),
    ("Staatsblad Tahun 1926 Nomor 226", None),
])
def test_cite_to_id(cite, work):
    assert bpk.cite_to_id(cite) == work


def test_detail_uu_4_2009():
    d = bpk.parse_detail(page("details_uu_4_2009.html"))
    m = d["meta"]
    assert m["Nomor"] == "4" and m["Tahun"] == "2009" and m["Bentuk Singkat"] == "UU"
    assert m["Judul"] == "Undang-undang (UU) Nomor 4 Tahun 2009 tentang Pertambangan Mineral dan Batubara"
    assert m["Tanggal Pengundangan"] == "12 Januari 2009"
    assert m["Sumber"].startswith("LN. 2009/ No. 4")
    assert d["files"] == [{"url": "https://peraturan.bpk.go.id/Download/27833/UU%20Nomor%204%20Tahun%202009.pdf",
                           "bpk_file_id": 27833, "filename": "UU Nomor 4 Tahun 2009.pdf"}]
    assert [u["putusan"] for u in d["uji_materi"]] == ["25/PUU-VII/2010"]
    assert "Pasal 22 huruf e" in d["uji_materi"][0]["amar"]
    s = d["status_peraturan"]
    assert [e["id"] for e in s["Diubah dengan"]] == [
        "uu_2_2025", "uu_6_2023", "perppu_2_2022", "uu_3_2020", "uu_11_2020"]
    assert s["Mencabut"][0]["id"] == "uu_11_1967"


def test_detail_status_notes_and_unlinked():
    s = bpk.parse_detail(page("details_uu_6_2023.html"))["status_peraturan"]
    partly = s["Dicabut sebagian dengan"][0]
    assert partly["id"] == "uu_27_2026" and partly["tentang"] == "Pelindungan Ketenagakerjaan"
    assert partly["note"].startswith("Bab IV Bagian Kesatu Pasal 80")
    assert any(e["id"] is None and e["citation"].startswith("Staatsblad") for e in s["Mencabut"])
    assert s["Diubah dengan"][0]["note"] is None


def test_update_existing_record_keeps_ours():
    d = bpk.parse_detail(page("details_uu_4_2009.html"))
    rec = {"id": "uu_4_2009", "tentang": "PERTAMBANGAN MINERAL DAN BATUBARA", "status": "berlaku",
           "tanggal_penetapan": "2009-01-12", "tempat_penetapan": "Jakarta", "year": 2009,
           "source_url": "https://peraturan.go.id/id/uu-no-4-tahun-2009",
           "source_pdf_url": "https://peraturan.go.id/files/uu4-2009bt.pdf", "versions": []}
    url = "https://peraturan.bpk.go.id/Details/38578/uu-no-4-tahun-2009"
    rec, notes = bpk.update_record(rec, d, "uu", url)
    assert notes == []
    assert rec["tentang"] == "PERTAMBANGAN MINERAL DAN BATUBARA"           # not overwritten
    assert rec["tanggal_pengundangan"] == "2009-01-12"
    assert rec["source_url"] == url and rec["source_pdf_url"].endswith("/Download/27833/UU%20Nomor%204%20Tahun%202009.pdf")
    assert rec["other_sources"] == [{"source_url": "https://peraturan.go.id/id/uu-no-4-tahun-2009",
                                     "source_pdf_url": "https://peraturan.go.id/files/uu4-2009bt.pdf"}]
    assert rec["bpk"]["id"] == 38578
    rec, _ = bpk.update_record(rec, d, "uu", url)                          # idempotent
    assert len(rec["other_sources"]) == 1


def test_differing_date_is_recorded_not_swapped():
    d = bpk.parse_detail(page("details_uu_4_2009.html"))
    rec = {"id": "uu_4_2009", "tanggal_penetapan": "2009-01-13", "year": 2009, "versions": []}
    rec, notes = bpk.update_record(rec, d, "uu", "https://peraturan.bpk.go.id/Details/38578/x")
    assert rec["tanggal_penetapan"] == "2009-01-13" and rec["tanggal_penetapan_bpk"] == "2009-01-12"
    assert notes and "differs" in notes[0]


def test_new_record():
    d = bpk.parse_detail(page("details_uu_5_2026.html"))
    rec, _ = bpk.update_record(None, d, "uu", "https://peraturan.bpk.go.id/Details/350096/uu-no-5-tahun-2026")
    assert rec["id"] == "uu_5_2026" and rec["akn"] == "/akn/id/act/uu/2026/5"
    assert rec["title"].startswith("Undang-Undang Nomor 5 Tahun 2026 tentang Perubahan Ketiga")
    assert rec["tanggal_penetapan"] == "2026-06-17" and rec["status"] == "berlaku"


class FakeResponse:
    def __init__(self, content: bytes, ctype: str):
        self.content, self.text = content, content.decode("latin-1")
        self.headers = {"content-type": ctype}


class FakeSession:
    """Serves the saved detail page and a small generated PDF; counts requests."""

    def __init__(self, detail: str, pdf: bytes):
        self.detail, self.pdf, self.calls = detail, pdf, []

    def get(self, url):
        self.calls.append(url)
        if "/Download/" in url:
            return FakeResponse(self.pdf, "application/pdf")
        return FakeResponse(page(self.detail).encode(), "text/html")


def small_pdf() -> bytes:
    import pymupdf

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "UNDANG-UNDANG REPUBLIK INDONESIA")
    return doc.tobytes()


def test_import_existing_record_keeps_text_and_records_pdf(tmp_path):
    import json

    import yaml

    folder = tmp_path / "peraturan" / "uu" / "2009" / "uu_4_2009"
    folder.mkdir(parents=True)
    (folder / "uu_4_2009_2009-01-12.txt").write_text("text from peraturan.go.id")
    rec = make_record("uu_4_2009", tentang="X", tanggal_penetapan="2009-01-12", status="berlaku",
                      source_url="https://peraturan.go.id/id/uu-no-4-tahun-2009",
                      source_pdf_url="https://peraturan.go.id/files/uu4-2009bt.pdf",
                      versions=[make_version("uu_4_2009", pasal_count=175)])
    (folder / "uu_4_2009.yaml").write_text(yaml.safe_dump(rec))
    s = FakeSession("details_uu_4_2009.html", small_pdf())
    item = bpk.Listing("/Details/38578/uu-no-4-tahun-2009", 38578)
    known: dict = {}

    line = bpk.import_one(s, item, "uu", tmp_path, known)
    # BPK's PDF is tried with the current parser; this one has no pasal, so the old text stays
    assert line.startswith("ok   uu_4_2009: 1 PDF recorded; kept old text")
    out = yaml.safe_load((folder / "uu_4_2009.yaml").read_text())
    assert (folder / "uu_4_2009_2009-01-12.txt").read_text() == "text from peraturan.go.id"
    assert out["versions"] == rec["versions"]
    assert out["bpk"]["files"][0]["sha256"] and out["tanggal_pengundangan"] == "2009-01-12"
    m = [json.loads(x) for x in (tmp_path / "sources" / "manifests" / "peraturan.bpk.go.id.jsonl")
         .read_text().splitlines()]
    assert m[0]["doc_id"] == "uu_4_2009_2009-01-12" and m[0]["archive_url"] is None
    assert m[0]["original_filename"] == "UU Nomor 4 Tahun 2009.pdf"

    n = len(s.calls)                       # resumes: nothing fetched again
    assert bpk.import_one(s, item, "uu", tmp_path, known).startswith("skip")
    assert len(s.calls) == n


def test_import_new_record(tmp_path):
    import yaml

    s = FakeSession("details_uu_5_2026.html", small_pdf())
    line = bpk.import_one(s, bpk.Listing("/Details/350096/uu-no-5-tahun-2026", 350096), "uu",
                          tmp_path, {})
    assert line.startswith("ok   uu_5_2026: 1 PDF recorded; no pasal found")
    rec = yaml.safe_load((tmp_path / "peraturan/uu/2026/uu_5_2026/uu_5_2026.yaml").read_text())
    assert rec["source_url"].endswith("/Details/350096/uu-no-5-tahun-2026")
    assert "other_sources" not in rec and rec["pdf_quality"] == "image_only_or_unparsed"


def test_not_a_pdf_fails_without_writing_manifest(tmp_path):
    s = FakeSession("details_uu_5_2026.html", b"<html>challenge</html>")
    with pytest.raises(RuntimeError, match="not a PDF"):
        bpk.import_one(s, bpk.Listing("/Details/350096/uu-no-5-tahun-2026", 350096), "uu",
                       tmp_path, {})
    assert not (tmp_path / "sources").exists()


def test_find_picks_the_exact_regulation():
    class S:
        def get(self, url):
            assert "&tahun=2026&jenis=8" in url and "nomor=" in url
            return FakeResponse(page("search_uu_p1.html").encode(), "text/html")

    assert bpk.find(S(), "uu_5_2026") == bpk.Listing("/Details/350096/uu-no-5-tahun-2026", 350096)
    with pytest.raises(LookupError):
        bpk.find(S(), "uu_99_2026")


def test_no_text_leaves_record_without_text(tmp_path):
    import yaml

    s = FakeSession("details_uu_5_2026.html", small_pdf())
    line = bpk.import_one(s, bpk.Listing("/Details/350096/uu-no-5-tahun-2026", 350096), "uu",
                          tmp_path, {}, no_text=True)
    assert line.endswith("PDFs only (no text step)")
    rec = yaml.safe_load((tmp_path / "peraturan/uu/2026/uu_5_2026/uu_5_2026.yaml").read_text())
    assert rec["versions"] == [] and "pdf_quality" not in rec


def test_never_replaced_by_a_poorer_text(tmp_path):
    import yaml

    from hukum_rapih.sources.peraturan_go_id import convert_pdf

    folder = tmp_path / "uu_9_2000"
    folder.mkdir()
    stored = "BODY\n" + "".join(f"  ART {n} -\n    kata.\n" for n in range(1, 41))
    (folder / "uu_9_2000_2000-01-01.txt").write_text(stored)
    rec = {"id": "uu_9_2000", "akn": "/akn/id/act/uu/2000/9", "year": 2000, "tanggal_penetapan": "2000-01-01",
           "versions": [{"id": "uu_9_2000_2000-01-01", "text": "uu_9_2000_2000-01-01.txt", "pasal_count": 40}]}
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    for k, t in enumerate(["Menimbang : a. bahwa x;", "Pasal 1", "satu.", "Pasal 2", "dua."]):
        page.insert_text((72, 72 + 20 * k), t)
    doc.save(tmp_path / "p.pdf")
    note = convert_pdf(tmp_path / "p.pdf", rec, folder, source="peraturan.bpk.go.id")
    assert note.startswith("kept old text (new text has 2 pasal, stored text 40)")
    assert (folder / "uu_9_2000_2000-01-01.txt").read_text() == stored and "stored text 40" in rec["reparse_error"]
    assert yaml.safe_dump(rec)


def test_reparse_from_archive_checks_the_hash(tmp_path, monkeypatch):
    import urllib.request

    import yaml

    from hukum_rapih.manifest import sha256_file

    pdf = tmp_path / "src.pdf"
    pdf.write_bytes(small_pdf())
    folder = tmp_path / "peraturan" / "uu" / "2026" / "uu_5_2026"
    folder.mkdir(parents=True)
    rec = make_record("uu_5_2026", bpk={"id": 1, "files": [
        {"url": "u", "bpk_file_id": 1, "filename": "f.pdf", "sha256": sha256_file(pdf),
         "archive_url": "https://archive.org/x"}]})
    (folder / "uu_5_2026.yaml").write_text(yaml.safe_dump(rec))
    monkeypatch.setattr(urllib.request, "urlretrieve", lambda url, dest: dest.write_bytes(pdf.read_bytes()))
    assert list(bpk.reparse(tmp_path)) == ["ok   uu_5_2026: reparsed, no pasal found (scanned PDF?)"]
    assert list(bpk.reparse(tmp_path)) == []                        # tried with this parser: done
    rec["parser_version_tried"] = 0
    rec["bpk"]["files"][0]["sha256"] = "0" * 64                    # archive copy is not what we recorded
    (folder / "uu_5_2026.yaml").write_text(yaml.safe_dump(rec))
    assert next(iter(bpk.reparse(tmp_path))).startswith("FAIL uu_5_2026: archived file differs")


def test_mirror_fallback_when_bpk_fails(tmp_path, monkeypatch):
    import json

    (tmp_path / "sources" / "mirrors").mkdir(parents=True)
    (tmp_path / "sources" / "mirrors" / "id_reg.json").write_text(json.dumps(
        {"files": {"UU_Nomor_5_Tahun_2026.pdf": ["batch-9-chunk-1.zip", 1]}}))
    monkeypatch.setattr(bpk, "from_mirror", lambda name, d: (small_pdf(), f"Azzindani/ID_REG batch-9-chunk-1.zip/{name}")
                        if name == "UU Nomor 5 Tahun 2026.pdf" else None)

    class Broken:
        def get(self, url):
            raise RuntimeError("giving up")

    content, note = bpk.download(Broken(), {"url": "u", "filename": "UU Nomor 5 Tahun 2026.pdf"}, tmp_path)
    assert content.startswith(b"%PDF") and "mirror" in note and "giving up" in note
    with pytest.raises(RuntimeError, match="not in the mirror either"):
        bpk.download(Broken(), {"url": "u", "filename": "UU Nomor 99 Tahun 2026.pdf"}, tmp_path)


# ---- the archive.org copies listed by the dharmasastra archive (decision 0029) ----------------

BPK_FILE = {"url": "https://peraturan.bpk.go.id/Download/1/UU%20Nomor%205%20Tahun%202026%20%28salinan%29.pdf",
            "bpk_file_id": 1, "filename": "UU Nomor 5 Tahun 2026 (salinan).pdf"}
COPY = "https://archive.org/download/peraturan-indonesia-uu-2026/uu_5_2026.pdf"


def mappings(*maps: dict) -> bytes:
    """A tarball of the archive's repository holding these mapping files."""
    import io
    import tarfile

    import yaml

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for n, m in enumerate(maps):
            data = yaml.safe_dump(m).encode()
            info = tarfile.TarInfo(f"idn-dharmasastra-archive-main/data/mapping/uu/m{n}.yaml")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def archive(monkeypatch, served: bytes, sha256: str, bpk_url: str) -> list[str]:
    """The archive maps ``bpk_url`` to COPY with ``sha256``; archive.org serves ``served``.
    Returns the URLs fetched from archive.org."""
    import httpx

    from hukum_rapih.sources import dharmasastra

    listed = dharmasastra.read_mappings(mappings(
        {"bpk_url": bpk_url, "archive_url": COPY, "sha256": sha256},
        {"bpk_url": "https://peraturan.bpk.go.id/Download/2/x.pdf", "archive_url": COPY}))   # upload running
    monkeypatch.setattr(dharmasastra, "copies", lambda: listed)
    fetched = []

    def get(url, **_):
        fetched.append(url)
        return httpx.Response(200, content=served, request=httpx.Request("GET", url))

    monkeypatch.setattr(dharmasastra.httpx, "get", get)
    return fetched


def test_archive_copy_is_used_when_its_hash_is_the_mappings(tmp_path, monkeypatch):
    pdf = small_pdf()
    # BPK's link and the mapping's spell the URL differently; decoded they are the same
    archive(monkeypatch, pdf, hashlib.sha256(pdf).hexdigest(),
            "https://peraturan.bpk.go.id/Download/1/UU Nomor 5 Tahun 2026 (salinan).pdf")
    s = FakeSession("details_uu_5_2026.html", b"%PDF other bytes")
    content, note = bpk.download(s, BPK_FILE, tmp_path)
    assert content == pdf and COPY in note and "idn-dharmasastra-archive" in note
    assert s.calls == []                                     # BPK not asked


def test_bpk_is_used_when_the_archive_copy_is_other_bytes(tmp_path, monkeypatch):
    pdf = small_pdf()
    archive(monkeypatch, b"%PDF damaged copy", hashlib.sha256(pdf).hexdigest(), BPK_FILE["url"])
    s = FakeSession("details_uu_5_2026.html", pdf)
    assert bpk.download(s, BPK_FILE, tmp_path) == (pdf, None)
    assert s.calls == [BPK_FILE["url"]]


def test_bpk_is_used_when_the_mapping_is_not_the_file_recorded(tmp_path, monkeypatch):
    pdf = small_pdf()
    fetched = archive(monkeypatch, pdf, hashlib.sha256(pdf).hexdigest(), BPK_FILE["url"])
    s = FakeSession("details_uu_5_2026.html", pdf)
    assert bpk.download(s, {**BPK_FILE, "sha256": "0" * 64}, tmp_path) == (pdf, None)
    assert fetched == [] and s.calls == [BPK_FILE["url"]]


def test_bpk_is_used_for_a_file_the_archive_does_not_list(tmp_path, monkeypatch):
    pdf = small_pdf()
    fetched = archive(monkeypatch, pdf, hashlib.sha256(pdf).hexdigest(),
                      "https://peraturan.bpk.go.id/Download/9/UU%20Nomor%209%20Tahun%202026.pdf")
    s = FakeSession("details_uu_5_2026.html", pdf)
    assert bpk.download(s, BPK_FILE, tmp_path) == (pdf, None)
    assert fetched == []


def test_hugging_face_comes_last(tmp_path, monkeypatch):
    pdf = small_pdf()
    archive(monkeypatch, b"%PDF damaged copy", hashlib.sha256(pdf).hexdigest(), BPK_FILE["url"])
    monkeypatch.setattr(bpk, "from_mirror", lambda name, d: (pdf, f"Azzindani/ID_REG z.zip/{name}"))

    class Broken:
        def get(self, url):
            raise RuntimeError("giving up")

    content, note = bpk.download(Broken(), BPK_FILE, tmp_path)
    assert content == pdf and "Azzindani/ID_REG" in note


def test_import_runs_as_before_when_the_mappings_cannot_be_read(tmp_path, monkeypatch):
    import httpx

    from hukum_rapih.sources import dharmasastra

    def down(url, **_):
        raise httpx.ConnectError("github.com did not answer")

    read_copies.cache_clear()
    monkeypatch.setattr(dharmasastra, "copies", read_copies)
    monkeypatch.setattr(dharmasastra.httpx, "get", down)
    pdf = small_pdf()
    s = FakeSession("details_uu_5_2026.html", pdf)
    assert bpk.download(s, BPK_FILE, tmp_path) == (pdf, None)
    read_copies.cache_clear()


def test_never_replaced_by_a_text_that_lost_its_penjelasan(tmp_path):
    from hukum_rapih.sources.peraturan_go_id import _poorer_than_stored

    stored = tmp_path / "t.txt"
    stored.write_text("BODY\n  ART 1 -\n    " + "kata " * 2000 + "\nATTACHMENT Penjelasan\n  " + "jelas " * 300)
    assert "Penjelasan has" in _poorer_than_stored(stored, "BODY\n  ART 1 -\n    " + "kata " * 2000, False)
    assert _poorer_than_stored(stored, "BODY\n  ART 1 -\n    " + "kata " * 1950 + "\nATTACHMENT Penjelasan\n  " + "jelas " * 290, False) is None
    assert "words, stored text" in _poorer_than_stored(stored, "BODY\n  ART 1 -\n    " + "kata " * 100, False)


def test_printed_promulgation_date_wins_over_bpk(tmp_path):              # UU 25/2007
    folder = tmp_path / "uu_25_2007"
    folder.mkdir()
    (folder / "t.txt").write_text("CONCLUSIONS\n  Disahkan di Jakarta\n\n  pada tanggal 26 April 2007\n\n"
                                  "  Diundangkan di Jakarta\n\n  pada tanggal 26 April 2007\n")
    rec = {"tanggal_penetapan": "2007-04-26", "tanggal_penetapan_bpk": "2008-04-26",
           "tanggal_pengundangan": "2008-04-26", "versions": [{"id": "v", "text": "t.txt"}]}
    notes = bpk.check_dates(rec, folder)
    assert rec["tanggal_pengundangan"] == "2007-04-26" and rec["bpk"]["tanggal_pengundangan"] == "2008-04-26"
    assert rec["tanggal_penetapan"] == "2007-04-26" and any("tanggal_penetapan_bpk" in n for n in notes)


def test_known_archive_copy_keeps_its_link(tmp_path):    # copies archived before 2026-11-24
    import yaml

    pdf = small_pdf()
    sha = hashlib.sha256(pdf).hexdigest()
    link = "https://archive.org/download/uu_5_2026/uu_5_2026_2026-06-17.pdf"
    s = FakeSession("details_uu_5_2026.html", pdf)
    bpk.import_one(s, bpk.Listing("/Details/350096/uu-no-5-tahun-2026", 350096), "uu", tmp_path, {},
                   cache={sha: link})
    rec = yaml.safe_load((tmp_path / "peraturan/uu/2026/uu_5_2026/uu_5_2026.yaml").read_text())
    assert rec["bpk"]["files"][0]["archive_url"] == link


def test_penjelasan_files_are_recognised_by_name():
    assert bpk.is_penjelasan({"filename": "UU Nomor 19 Tahun 2003_ penjelasan.pdf"})
    assert bpk.is_penjelasan({"filename": "PENJELASAN UU 5 2010.pdf"})
    assert not bpk.is_penjelasan({"filename": "undang-undang nomor 19 tahun 2003.pdf"})
    assert not bpk.is_penjelasan({})
