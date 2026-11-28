"""peraturan.bpk.go.id (Database Peraturan JDIH BPK): listing -> detail -> PDFs -> the manifest
(sha256) -> text, the main source for regulations since 2026-11-21.

Per regulation (docs/NAMING.md):
    data/peraturan/<jenis>/<tahun>/<id>/<id>.yaml        record (created, or updated)
    data/peraturan/<jenis>/<tahun>/<id>/<version>.txt    text, when the record has none yet
and per PDF one line in data/sources/manifests/peraturan.bpk.go.id.jsonl (sha256; PDFs are not
kept or uploaded anywhere since 2026-11-24, but copies archived earlier stay linked).

Records imported earlier from peraturan.go.id keep their text: the BPK PDF is
parsed for comparison only (``bpk.pasal_count``); switching texts is a separate decision.
Their peraturan.go.id links move to ``other_sources``. Metadata already in a record is never
overwritten with a blank, and a differing date is recorded next to ours, not swapped in.

The site sits behind Cloudflare; see bpk_session.py.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from ..naming import work_uri
from ..records import load_record, save_record
from .bpk_session import BASE

SOURCE = "peraturan.bpk.go.id"
JENIS_ID = {"uu": 8, "perppu": 9, "pp": 10, "perpres": 11}    # BPK's "jenis" filter values
BENTUK = {"uu": "uu", "perpu": "perppu", "perppu": "perppu", "pp": "pp", "perpres": "perpres",
          "keppres": "keppres"}
JENIS_TITLE = {"uu": "Undang-Undang", "perppu": "Peraturan Pemerintah Pengganti Undang-Undang",
               "pp": "Peraturan Pemerintah", "perpres": "Peraturan Presiden",
               "keppres": "Keputusan Presiden"}
# Entries imported one by one instead of from a listing (decision 0027: Keppres are otherwise
# not imported). BPK detail page paths.
ONE_OFF = {"keppres": ["/Details/96516"]}
STATUS = {"berlaku": "berlaku", "tidak berlaku": "tidak_berlaku", "dicabut": "dicabut",
          "diubah": "diubah"}


# ---- parsing -------------------------------------------------------------------------------

def clean(fragment: str) -> str:
    """HTML fragment -> plain text on one line."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class Listing:
    path: str      # /Details/38578/uu-no-4-tahun-2009
    bpk_id: int


def parse_listing(text: str) -> list[Listing]:
    # each result's heading link ("Undang-undang (UU) Nomor 5 Tahun 2026"); the status lines
    # under a result link to related regulations, which are not results themselves
    paths = dict.fromkeys(re.findall(
        r'<a class="text-gray-600 text-decoration-none" href="(/Details/\d+/[^"#?]+)"', text))
    return [Listing(p, int(p.split("/")[2])) for p in paths]


def last_page(text: str) -> int:
    pages = [int(p) for p in re.findall(r"[?&](?:amp;)?p=(\d+)", text)]
    return max(pages, default=1)


def cite_to_id(citation: str) -> str | None:
    """'UU No. 2 Tahun 2025' -> 'uu_2_2025'; 'PERPU No. 2 Tahun 2022' -> 'perppu_2_2022'."""
    m = re.match(r"\s*(UU|PERPU|PERPPU|PP|PERPRES)\s+No\.?\s*([0-9]+[A-Za-z]?)\s+Tahun\s+(\d{4})\s*$",
                 citation, re.IGNORECASE)
    return f"{BENTUK[m[1].lower()]}_{m[2].lower()}_{m[3]}" if m else None


def _attrs(tag: str) -> dict[str, str]:
    return {k: html.unescape(v) for k, v in re.findall(r'([\w-]+)="([^"]*)"', tag)}


def parse_detail(text: str) -> dict:
    """Detail page -> {'meta': {label: value}, 'files', 'uji_materi', 'status_peraturan'}."""
    meta = {}
    for label, value in re.findall(
        r'<div class="col-lg-3 fw-bold">(.*?)</div>\s*<div class="col-lg-9">(.*?)</div>', text, re.DOTALL
    ):
        meta[clean(label)] = clean(value)

    files = []
    for tag in re.findall(r"<a\b[^>]*>", text):
        a = _attrs(tag)
        if a.get("data-kategori") == "Peraturan" and a.get("href", "").startswith("/Download/"):
            files.append({"url": BASE + a["href"], "bpk_file_id": int(a["data-id"]),
                          "filename": unquote(a["href"].rsplit("/", 1)[-1])})

    uji_materi = []
    for tag, putusan, rest in re.findall(
        r'(<a\b[^>]*data-kategori="UjiMateri"[^>]*>)(.*?)</a>(.*?)(?=data-kategori="UjiMateri"|UJI MATERI|$)',
        text, re.DOTALL,
    ):
        amar = re.search(r"<span>(.*?)</span>", rest, re.DOTALL)
        uji_materi.append({"putusan": clean(putusan), "url": BASE + _attrs(tag)["href"],
                           "amar": clean(amar[1]) if amar else None})

    status: dict[str, list[dict]] = {}
    block = text[text.find("STATUS <span"):]
    block = block[: block.find("ABSTRAK <span")] if "ABSTRAK <span" in block else block
    for heading, items in re.findall(
        r'<div class="col-12 fw-semibold bg-light-primary p-4">\s*(.*?)\s*</div>.*?<ol[^>]*>(.*?)</ol>',
        block, re.DOTALL,
    ):
        entries = []
        for li in re.findall(r"<li[^>]*>(.*?)</li>", items, re.DOTALL):
            link = re.search(r'<a[^>]*href="(/Details/[^"]+)"[^>]*>(.*?)</a>', li, re.DOTALL)
            note = re.search(r"<br\s*/?>\s*<span>(.*?)</span>", li, re.DOTALL)
            body = re.sub(r"<br\s*/?>\s*<span>.*?</span>", "", li, flags=re.DOTALL)
            if link:
                citation = clean(link[2])
                tentang = clean(body.split("</a>", 1)[1]).removeprefix("tentang").strip()
                entries.append({"id": cite_to_id(citation), "citation": citation,
                                "tentang": tentang or None, "url": BASE + link[1],
                                "note": (clean(note[1]) or None) if note else None})
            else:
                entries.append({"id": None, "citation": clean(body), "tentang": None,
                                "url": None, "note": (clean(note[1]) or None) if note else None})
        status[clean(heading).rstrip(" :")] = entries
    return {"meta": meta, "files": files, "uji_materi": uji_materi, "status_peraturan": status}


def work_id(meta: dict, jenis: str) -> str:
    from ..naming import validate_id

    bentuk = BENTUK.get(meta.get("Bentuk Singkat", "").lower(), jenis)
    nomor = re.sub(r"\s+", "", meta.get("Nomor", "")).lower()
    return validate_id(f"{bentuk}_{nomor}_{meta.get('Tahun', '')}")


# ---- records -------------------------------------------------------------------------------

def update_record(rec: dict | None, d: dict, jenis: str, detail_url: str) -> tuple[dict, list[str]]:
    """Merge a parsed detail page into a record (new if ``rec`` is None). Returns the record
    and notes for the log (e.g. dates that differ from ours)."""
    from .peraturan_go_id import tanggal_iso

    meta, notes = d["meta"], []
    work = work_id(meta, jenis)
    w_jenis, nomor, tahun = work.split("_")
    judul = meta.get("Judul", "")
    tentang = judul.split(" tentang ", 1)[1].strip() if " tentang " in judul else None
    if rec is None:
        rec = {
            "id": work, "akn": f"/akn/id/act/{w_jenis}/{tahun}/{nomor}", "type": w_jenis,
            "number": nomor, "year": int(tahun),
            "title": f"{JENIS_TITLE.get(w_jenis, w_jenis.upper())} Nomor {nomor.upper()} Tahun {tahun}"
                     + (f" tentang {tentang}" if tentang else ""),
            "tentang": tentang, "short_name": None, "status": None,
            "tanggal_penetapan": None, "tempat_penetapan": None, "pejabat_penetapan": None,
            "pemrakarsa": None, "source_url": None, "source_pdf_url": None,
            "relationships": {"amends": [], "amended_by": [], "revokes": [], "revoked_by": []},
            "versions": [],
        }
    elif rec["id"] != work:
        raise ValueError(f"BPK page is {work}, record is {rec['id']}")

    def fill(key: str, value) -> None:            # never blank out what we have
        if value and not rec.get(key):
            rec[key] = value

    fill("tentang", tentang)
    fill("tempat_penetapan", meta.get("Tempat Penetapan"))
    penetapan = tanggal_iso(meta.get("Tanggal Penetapan", ""))
    if penetapan and rec.get("tanggal_penetapan") and str(rec["tanggal_penetapan"]) != penetapan:
        rec["tanggal_penetapan_bpk"] = penetapan
        notes.append(f"tanggal penetapan differs: ours {rec['tanggal_penetapan']}, BPK {penetapan}")
    fill("tanggal_penetapan", penetapan)
    for key, label in (("tanggal_pengundangan", "Tanggal Pengundangan"),
                       ("tanggal_berlaku", "Tanggal Berlaku")):
        if iso := tanggal_iso(meta.get(label, "")):
            rec[key] = iso
    for key, label in (("lembaran_negara", "Sumber"), ("subjek", "Subjek")):
        if meta.get(label):
            rec[key] = meta[label]
    if status := STATUS.get(meta.get("Status", "").lower()):
        rec["status"] = status

    # BPK becomes the primary source; earlier sources are kept
    old = {"source_url": rec.get("source_url"), "source_pdf_url": rec.get("source_pdf_url")}
    if old["source_url"] and SOURCE not in old["source_url"]:
        others = rec.setdefault("other_sources", [])
        if old not in others:
            others.append(old)
    rec["source_url"] = detail_url
    rec["source_pdf_url"] = d["files"][0]["url"] if d["files"] else None
    bpk = rec.setdefault("bpk", {})
    bpk["id"] = int(detail_url.split("/")[4])
    old_files = {f["url"]: f for f in bpk.get("files", [])}
    bpk["files"] = [{**old_files.get(f["url"], {}), **f} for f in d["files"]]
    bpk["status_peraturan"] = d["status_peraturan"] or None
    rec["uji_materi"] = d["uji_materi"] or None
    return rec, notes


def check_dates(rec: dict, folder: Path) -> list[str]:
    """Compare BPK's dates with the ones printed in the law's closing. The printed date is
    the evidence: when they differ, the record takes it and keeps BPK's under ``bpk``
    (UU 25/2007: BPK says 26 April 2008, the law says 2007)."""
    from ..closing import conclusions, parse
    from .peraturan_go_id import tanggal_iso

    texts = [v for v in rec.get("versions") or [] if v.get("text")]
    if not texts or not (folder / texts[0]["text"]).exists():
        return []
    c = parse(conclusions((folder / texts[0]["text"]).read_text()))

    def printed(block: str) -> str | None:
        return tanggal_iso(re.sub(r"^tanggal\s+", "", (c.get(block) or {}).get("date") or ""))

    notes = []
    signed = printed("signed")
    for key in ("tanggal_penetapan", "tanggal_penetapan_bpk"):           # ids depend on it: note only
        if signed and rec.get(key) and str(rec[key]) != signed:
            notes.append(f"{key} {rec[key]} differs from the printed {signed}")
    promulgated = printed("promulgated")
    if promulgated and rec.get("tanggal_pengundangan") and str(rec["tanggal_pengundangan"]) != promulgated:
        rec.setdefault("bpk", {})["tanggal_pengundangan"] = str(rec["tanggal_pengundangan"])
        notes.append(f"tanggal_pengundangan: printed {promulgated}, BPK {rec['tanggal_pengundangan']}")
        rec["tanggal_pengundangan"] = promulgated
    return notes


def record_path(data_dir: Path, work: str) -> Path:
    parts = work.split("_")                     # uu_4_2009, or uud_1945 (no number)
    return data_dir / "peraturan" / parts[0] / parts[-1] / work / f"{work}.yaml"


SIGNED_ON = re.compile(r"Ditetapkan\s+di\s+\w+\s*,?\s+pada\s+tanggal\s+(\d{1,2}\s+\w+\s+\d{4})",
                       re.IGNORECASE)   # the MPR's amendments print "Pada tanggal"
# months as printed before 1972 ("5 Djuli 1959"), read as today's names to find the date
OLD_MONTHS = {"djanuari": "januari", "pebruari": "februari", "djuni": "juni", "djuli": "juli",
              "nopember": "november"}
OLD_MONTH = re.compile("|".join(OLD_MONTHS), re.IGNORECASE)


def date_printed(rec: dict, folder: Path) -> list[str]:
    """For a record with no date at all (BPK gives none for the UUD and Keppres 150/1959): the
    date its text prints after "Ditetapkan di … pada tanggal", and its text version re-dated
    to it (docs/NAMING.md). A text that prints none keeps the bare year; nothing is guessed."""
    from .peraturan_go_id import tanggal_iso

    texts = [v for v in rec.get("versions") or [] if v.get("text")]
    if rec.get("tanggal_penetapan") or len(texts) != 1 or not (folder / texts[0]["text"]).exists():
        return []
    flat = re.sub(r"\s+", " ", re.sub(r"\\(.)", r"\1", (folder / texts[0]["text"]).read_text()))
    found = [iso for iso in (tanggal_iso(OLD_MONTH.sub(lambda m: OLD_MONTHS[m[0].lower()], d))
                             for d in SIGNED_ON.findall(flat)) if iso]
    if not found:
        return [f"{rec['id']}: no date printed, kept {rec['year']}"]
    rec["tanggal_penetapan"] = found[-1]          # the closing comes last
    v = texts[0]
    version = f"{rec['id']}_{found[-1]}"
    (folder / v["text"]).rename(folder / f"{version}.txt")
    v.update(id=version, date=found[-1], text=f"{version}.txt")
    return [f"{rec['id']}: dated {found[-1]} as printed"]


def files_done(rec: dict) -> bool:
    """Every BPK file of the record is downloaded and its hash recorded."""
    files = (rec.get("bpk") or {}).get("files") or []
    return bool(files) and all(f.get("sha256") for f in files)


def text_current(rec: dict) -> bool:
    """Nothing for the current parser to do: the text comes from BPK's PDF and a parser no
    older than PARSER_REDO_BELOW, and the record is not flagged; or the current parser was
    already tried on it (kept old text, parse error, or no text: scanned and unreadable)."""
    from ..pdf.structure import OCR_REDO_BELOW, PARSER_REDO_BELOW, PARSER_VERSION

    if (str(rec.get("reparse_error", "")).startswith(f"v{PARSER_VERSION}:")
            or rec.get("parser_version_tried") == PARSER_VERSION):
        return True
    if rec.get("reparse_error") or rec.get("parse_error") or rec.get("recheck"):
        return False                                     # flagged (by an older parser or by
        #                                                  scripts/check_texts.py --flag): try again
    from ..pdf.extract import ocr_engine

    texts = [v for v in rec.get("versions") or [] if v.get("text")]
    return bool(texts) and all((v.get("parser_version") or 0)
                               >= (OCR_REDO_BELOW if v.get("ocr") else PARSER_REDO_BELOW)
                               and v.get("pdf_source") == SOURCE
                               # a text another OCR engine read is redone with the current one
                               # (decision 0012: Tesseract -> Indra); typed texts are not
                               and (not v.get("ocr") or v.get("ocr_engine", "tesseract") == ocr_engine())
                               for v in texts)


def is_penjelasan(f: dict) -> bool:
    """A file holding only the Penjelasan of the law ("UU Nomor 19 Tahun 2003_ penjelasan.pdf")."""
    return "penjelasan" in (f.get("filename") or "").lower()


def order_problems(order: dict, files: list[dict]) -> list[str]:
    """How a file order (``FileOrder`` in records.py) fails to name each of ``files`` exactly
    once, in ``order`` or in ``skip``; empty when it does."""
    named = Counter(order["order"] + [s["bpk_file_id"] for s in order["skip"]])
    ids = {f["bpk_file_id"] for f in files}
    return ([f"{i} is not a file of the law" for i in named if i not in ids]
            + [f"{i} is named {n} times" for i, n in named.items() if n > 1]
            + [f"{i} is neither ordered nor skipped" for i in sorted(ids - set(named))])


def current_order(bpk: dict) -> dict | None:
    """The routine's ``file_order`` while it still names exactly the files BPK lists; BPK can
    add or drop a file later, and the law then goes back to the queue."""
    order = bpk.get("file_order")
    return order if order and not order_problems(order, bpk.get("files") or []) else None


def files_to_read(bpk: dict) -> list[dict]:
    """The BPK files of a law that are joined into its text, in reading order (decision 0023):
    those of ``current_order``, the skipped ones left out; without one, the first file not
    named a Penjelasan, then the Penjelasan files."""
    files = bpk.get("files") or []
    if order := current_order(bpk):
        by_id = {f["bpk_file_id"]: f for f in files}
        return [by_id[i] for i in order["order"]]
    main = [f for f in files if not is_penjelasan(f)][:1] or files[:1]
    return main + [f for f in files if is_penjelasan(f) and f is not main[0]]


NO_PDF_RECHECK_DAYS = 7   # a law BPK lists without a PDF is looked at again after this


def no_pdf_lately(rec: dict) -> bool:
    """BPK was checked lately and lists no PDF for the law: nothing to do until the recheck.
    Without this, such laws were fetched again in every batch (3 of them took 9 batches,
    ~2 h, on 2026-11-23)."""
    from datetime import date

    bpk = rec.get("bpk") or {}
    checked = bpk.get("no_pdf_checked")
    return (bpk.get("files") == [] and bool(checked)
            and (date.today() - date.fromisoformat(str(checked))).days < NO_PDF_RECHECK_DAYS)


def done(rec: dict) -> bool:
    return no_pdf_lately(rec) or (files_done(rec) and text_current(rec))


def retext(pdf: Path, rec: dict, folder: Path, extra: list[Path] | None = None) -> str:
    """Convert BPK's PDF to the record's text with the current parser, unless that was done.
    A stored text is only replaced by a valid one with at least as many pasal (convert_pdf)."""
    from ..pdf.structure import PARSER_VERSION
    from .peraturan_go_id import convert_pdf

    if text_current(rec):
        return "text current"
    note = convert_pdf(pdf, rec, folder, source=SOURCE, extra=extra)
    if not any(v.get("text") for v in rec.get("versions") or []):
        rec["parser_version_tried"] = PARSER_VERSION
    return note


# ---- copies archived earlier ---------------------------------------------------------------

def archive_urls(data_dir: Path) -> dict[str, str]:
    """From the manifests: sha256 -> archive_url of copies archived before 2026-11-24, so a file
    already there keeps its link."""
    from ..manifest import records

    out = {}
    for r in records(data_dir):
        if r.get("archive_url"):
            out.setdefault(r["sha256"], r["archive_url"])
    return out


# ---- import --------------------------------------------------------------------------------

MIRROR = "https://huggingface.co/datasets/Azzindani/ID_REG/resolve/main/"


def download(session, f: dict, data_dir: Path) -> tuple[bytes, str | None]:
    """A BPK file's bytes: its archive.org copy when the dharmasastra archive lists one with the
    right sha256 (decision 0029), else from BPK, or when that fails, the file of the same name in
    the Hugging Face mirror of BPK (data/sources/mirrors/id_reg.json). Returns (bytes, note);
    the note names the mirror, None for BPK."""
    from . import dharmasastra

    if got := dharmasastra.fetch(f):
        return got
    try:
        r = session.get(f["url"])
        if r.content[:5].startswith(b"%PDF"):
            return r.content, None
        problem = f"not a PDF ({r.headers.get('content-type')})"
    except Exception as e:
        from .bpk_session import Challenged

        if isinstance(e, Challenged):
            raise
        problem = f"{type(e).__name__}: {str(e)[:120]}"
    got = from_mirror(f["filename"], data_dir)
    if got is None:
        raise RuntimeError(f"{f['url']}: {problem}; not in the mirror either")
    content, where = got
    return content, f"BPK download failed ({problem}); bytes from Hugging Face mirror {where}"


def from_mirror(filename: str, data_dir: Path) -> tuple[bytes, str] | None:
    index = data_dir / "sources" / "mirrors" / "id_reg.json"
    if not index.exists():
        return None
    member = filename.replace(" ", "_")
    hit = json.loads(index.read_text())["files"].get(member)
    if not hit:
        return None
    from remotezip import RemoteZip

    with RemoteZip(MIRROR + hit[0]) as z:
        content = z.read(member)
    return (content, f"Azzindani/ID_REG {hit[0]}/{member}") if content[:5].startswith(b"%PDF") else None


def listings(session, jenis: str, cache: Path | None = None) -> Iterator[Listing]:
    """Every regulation of ``jenis`` in BPK's listing, newest first. ``cache``: a folder that
    keeps the listing pages, so later batches of one workflow run read them from disk instead
    of walking ~190 pages again (~9.5 min a batch); a new run starts with an empty folder."""
    page, last = 1, 1
    while page <= last:
        saved = cache / f"{jenis}_{page}.html" if cache else None
        if saved and saved.exists():
            text = saved.read_text()
        else:
            text = session.get(f"/Search?jenis={JENIS_ID[jenis]}&p={page}").text
            if saved:
                saved.write_text(text)
        last = max(last, last_page(text))
        items = parse_listing(text)
        if not items:
            return
        yield from items
        page += 1


SLUG = {"uu": "uu", "perppu": "perpu", "pp": "pp", "perpres": "perpres"}


def find(session, work: str) -> Listing:
    """BPK detail page of one regulation, via the search form (nomor + tahun + jenis)."""
    jenis, nomor, tahun = work.split("_")
    text = session.get(f"/Search?keywords=&tentang=&nomor={nomor}&tahun={tahun}"
                       f"&jenis={JENIS_ID[jenis]}").text
    want = re.compile(rf"^/Details/\d+/{SLUG[jenis]}-no-{re.escape(nomor)}-tahun-{tahun}(?:-|$)")
    hits = [i for i in parse_listing(text) if want.match(i.path)]
    if len(hits) != 1:
        raise LookupError(f"{work}: {len(hits)} matching results on BPK")
    return hits[0]


def import_one(session, item: Listing, jenis: str, data_dir: Path, known: dict[int, Path],
               cache: dict[str, str] | None = None, no_text: bool = False) -> str:
    """Fetch one detail page, update or create the record, download its PDFs (hash recorded), and
    convert the main PDF when the record has no text (not with ``no_text``: PDFs only, e.g.
    to collect samples while the parser is being fixed). ``known``: bpk id -> record path."""
    from ..manifest import entry_for_file, manifest_path

    path = known.get(item.bpk_id)
    if path and done(load_record(path)):
        return f"skip {path.stem}: already from BPK"
    detail_url = BASE + item.path
    d = parse_detail(session.get(item.path).text)
    if not d["meta"].get("Nomor"):
        return f"skip {item.path}: no metadata"
    work = work_id(d["meta"], jenis)
    path = record_path(data_dir, work)
    existing = load_record(path) if path.exists() else None
    rec, notes = update_record(existing, d, jenis, detail_url)
    if not d["files"]:
        from datetime import date

        rec["bpk"]["no_pdf_checked"] = date.today().isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    save_record(path, rec)   # metadata first
    known[item.bpk_id] = path
    if not d["files"]:
        return f"ok   {work}: no PDF on BPK" + "".join(f"; {n}" for n in notes)

    by_sha = archive_urls(data_dir) if cache is None else cache
    texts = [v for v in rec.get("versions") or [] if v.get("text")]
    version = texts[0]["id"] if texts else f"{work}_{rec.get('tanggal_penetapan') or rec['year']}"
    with tempfile.TemporaryDirectory() as tmp:
        pdfs: dict[int, Path] = {}                  # bpk_file_id -> the downloaded copy
        for n, f in enumerate(rec["bpk"]["files"], start=1):
            pdf = Path(tmp) / f"{n}.pdf"
            content, mirror_note = download(session, f, data_dir)
            pdf.write_bytes(content)
            entry = entry_for_file(pdf, f["url"], None, None, f["filename"])
            archive_url = by_sha.get(entry.sha256)   # a copy archived before 2026-11-24
            doc_id = version if n == 1 else f"{version}_{n}"
            entry = entry_for_file(pdf, f["url"], archive_url, doc_id, f["filename"])
            if mirror_note:
                from dataclasses import replace
                entry = replace(entry, note=mirror_note)
                f["fetched_from"] = mirror_note
            manifest = manifest_path(data_dir, f["url"])
            manifest.parent.mkdir(parents=True, exist_ok=True)
            with manifest.open("a") as fh:
                fh.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
            f.update(sha256=entry.sha256, bytes=entry.bytes, archive_url=archive_url)
            pdfs[f["bpk_file_id"]] = pdf
        read = [pdfs[f["bpk_file_id"]] for f in files_to_read(rec["bpk"])]
        note = "PDFs only (no text step)" if no_text else retext(read[0], rec, path.parent, read[1:])
        notes += check_dates(rec, path.parent)
        if jenis in ONE_OFF:
            notes += date_printed(rec, path.parent)
    save_record(path, rec)
    return (f"ok   {work}: {len(rec['bpk']['files'])} PDF recorded; {note}"
            + "".join(f"; {n}" for n in notes))


# ---- the UUD 1945 (decision 0027) ------------------------------------------------------------

# One BPK entry holds the UUD, its four amendments and the MPR's consolidated text.
UUD_ENTRY = "/Details/101646/uud-no---uud-1945-dan-amandemen"
UUD_BPK_ID = int(UUD_ENTRY.split("/")[2])
UUD_TITLE = "Undang-Undang Dasar Negara Republik Indonesia Tahun 1945"
UUD_FILES = {"UUD45.pdf": "uud_1945",                   # BPK's file -> our work (docs/NAMING.md)
             "UUD45_perubahan1.pdf": "uud-perubahan_1_1999",
             "UUD45_perubahan2.pdf": "uud-perubahan_2_2000",
             "UUD45_perubahan3.pdf": "uud-perubahan_3_2001",
             "UUD45_perubahan4.pdf": "uud-perubahan_4_2002"}
SATU_NASKAH = "UUD45_SatuNaskah.pdf"   # the consolidated text: only checks the merged version
SATU_NASKAH_TEXT = "uud_1945_satu-naskah.txt"
ORDINAL_WORD = {1: "Pertama", 2: "Kedua", 3: "Ketiga", 4: "Keempat"}


def uud_record(work: str, detail_url: str) -> dict:
    """A new record for the UUD 1945 (no number) or one of its amendments."""
    jenis, *_, tahun = work.split("_")
    akn = work_uri(work)
    if work == "uud_1945":
        nomor, title = None, UUD_TITLE
    else:
        nomor = work.split("_")[1]
        title = f"Perubahan {ORDINAL_WORD[int(nomor)]} {UUD_TITLE}"
    return {
        "id": work, "akn": akn, "type": jenis, "number": nomor, "year": int(tahun), "title": title,
        "tentang": None, "short_name": None, "status": None, "tanggal_penetapan": None,
        "tempat_penetapan": None, "pejabat_penetapan": None, "pemrakarsa": None,
        "source_url": detail_url, "source_pdf_url": None,
        "relationships": {"amends": [], "amended_by": [], "revokes": [], "revoked_by": []},
        "versions": [],
    }


def import_uud(session, data_dir: Path, check_dir: Path | None = None) -> Iterator[str]:
    """The UUD 1945 and its four amendments from BPK's one entry: a record and text each, dated
    only by what the text prints. The consolidated text is parsed into ``check_dir`` (outside
    data/, on the runner) for ``scripts/check_uud.py``, never stored as a version; the PDFs are
    copied there too, for the workflow's review dump."""
    files = {f["filename"]: f for f in parse_detail(session.get(UUD_ENTRY).text)["files"]}
    if missing := sorted({*UUD_FILES, SATU_NASKAH} - set(files)):
        yield f"FAIL {UUD_ENTRY}: BPK lists no {', '.join(missing)} (it lists {', '.join(files)})"
    with tempfile.TemporaryDirectory() as tmp:
        pdfs: dict[str, Path] = {}
        for name in files.keys() & {*UUD_FILES, SATU_NASKAH}:
            content, mirror_note = download(session, files[name], data_dir)
            pdfs[name] = Path(tmp) / name
            pdfs[name].write_bytes(content)
            if mirror_note:
                files[name]["fetched_from"] = mirror_note
        for name, work in UUD_FILES.items():
            if name in pdfs:
                owned = [name, SATU_NASKAH] if work == "uud_1945" and SATU_NASKAH in pdfs else [name]
                yield _import_uud_work(work, [(files[n], pdfs[n]) for n in owned], data_dir)
        if check_dir:
            yield from _write_check(pdfs, check_dir)


def _import_uud_work(work: str, owned: list[tuple[dict, Path]], data_dir: Path) -> str:
    """One record of the UUD entry: its BPK files with their downloaded copies (the first one is
    its text), hashed into the manifest, and its text converted and dated."""
    path = record_path(data_dir, work)
    rec = load_record(path) if path.exists() else uud_record(work, BASE + UUD_ENTRY)
    old = {f["url"]: f for f in (rec.get("bpk") or {}).get("files", [])}
    rec["source_pdf_url"] = owned[0][0]["url"]
    rec["bpk"] = {**(rec.get("bpk") or {}), "id": UUD_BPK_ID,
                  "files": [_hashed(f, pdf, old.get(f["url"], {}), data_dir) for f, pdf in owned]}
    path.parent.mkdir(parents=True, exist_ok=True)
    save_record(path, rec)                              # metadata first
    note = retext(owned[0][1], rec, path.parent)
    notes = date_printed(rec, path.parent)
    save_record(path, rec)
    return f"ok   {work}: {note}" + "".join(f"; {n}" for n in notes)


def _hashed(f: dict, pdf: Path, recorded: dict, data_dir: Path) -> dict:
    """A record's entry for a downloaded BPK file, with its hash; a manifest line is added only
    for a file not recorded before, so re-running the import adds none."""
    from ..manifest import entry_for_file, manifest_path

    entry = entry_for_file(pdf, f["url"], None, None, f["filename"])
    if recorded.get("sha256") != entry.sha256:
        manifest = manifest_path(data_dir, f["url"])
        manifest.parent.mkdir(parents=True, exist_ok=True)
        with manifest.open("a") as fh:
            fh.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
    return {**recorded, **f, "sha256": entry.sha256, "bytes": entry.bytes}


def _write_check(pdfs: dict[str, Path], check_dir: Path) -> Iterator[str]:
    """The PDFs and the parsed consolidated text, on the runner only."""
    from ..akn.bluebell import to_bluebell
    from ..pdf.structure import parse_pdf

    check_dir.mkdir(parents=True, exist_ok=True)
    for name, pdf in pdfs.items():
        shutil.copyfile(pdf, check_dir / name)
    if SATU_NASKAH in pdfs:
        doc = parse_pdf(pdfs[SATU_NASKAH])
        (check_dir / SATU_NASKAH_TEXT).write_text(to_bluebell(doc))
        yield f"ok   {SATU_NASKAH}: {doc.pasal_count} pasal, for the check only"


def known_records(data_dir: Path) -> dict[int, Path]:
    """bpk id -> record path, for records already linked to BPK."""
    out = {}
    for path in (data_dir / "peraturan").glob("*/*/*/*.yaml"):
        rec = load_record(path)
        if (rec.get("bpk") or {}).get("id"):
            out[int(rec["bpk"]["id"])] = path
    return out


def reparse(data_dir: Path, only: set[str] | None = None) -> Iterator[str]:
    """Re-convert texts from the PDFs we archived on archive.org (no BPK, no Cloudflare): for
    records whose BPK files are all archived but whose text is not from the current parser.
    The download is checked against the hash recorded at import."""
    import urllib.request

    from ..manifest import sha256_file

    for path in sorted((data_dir / "peraturan").glob("*/*/*/*.yaml")):
        rec = load_record(path)
        if only and rec["id"] not in only:
            continue
        wanted = files_to_read(rec.get("bpk") or {})
        if not wanted:
            continue
        if not files_done(rec) or text_current(rec) or not all(f.get("archive_url") for f in wanted):
            continue
        with tempfile.TemporaryDirectory() as tmp:
            pdfs, failed = [], None
            for n, f in enumerate(wanted):
                pdf = Path(tmp) / f"{n}.pdf"
                try:
                    urllib.request.urlretrieve(f["archive_url"], pdf)
                except Exception as e:  # noqa: BLE001 - keep going; resumable
                    failed = f"archive.org: {e}"
                    break
                got = sha256_file(pdf)
                if got not in {f.get("sha256"), f.get("archived_sha256")}:
                    failed = f"archived file differs from the one recorded ({got[:12]})"
                    break
                pdfs.append(pdf)
            if failed:
                yield f"FAIL {rec['id']}: {failed}"
                continue
            note = retext(pdfs[0], rec, path.parent, pdfs[1:])
        save_record(path, rec)
        yield f"ok   {rec['id']}: reparsed, {note}"
