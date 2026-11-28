"""Bluebell text -> Akoma Ntoso XML, using Laws.Africa's bluebell parser."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..history import took_effect
from ..records import load_record
from ..yamlio import load_yaml
from .meta import LawContext, add_context

LANGUAGE = "ind"


class LeakedMarkupError(ValueError):
    """Bluebell markup ended up as visible text: the source text is malformed (usually a
    POINT/PARA indented at the wrong depth)."""


def to_akn_tree(text: str, frbr_uri: str, root: str = "act", expression_date: str | None = None,
                title: str | None = None, work_date: str | None = None):
    """The Akoma Ntoso document as an lxml element (``to_akn`` writes it out).

    ``work_date``: the full date of the Work (a law's tanggal penetapan). cobalt fills the
    Work's FRBRdate with the URI's bare year ("2009"), which the AKN 3.0 schema rejects
    (scripts/validate_akn.py); without a full date the year stays."""
    from bluebell.parser import AkomaNtosoParser
    from cobalt import FrbrUri

    uri = FrbrUri.parse(frbr_uri)
    uri.language = LANGUAGE
    if expression_date:
        uri.expression_date = f"@{expression_date}"
    parser = AkomaNtosoParser(uri)
    xml = parser.parse_to_xml(text, root)
    _check_no_leaked_markup(xml, _lampiran_eids(text))
    if work_date and len(work_date) == 10:
        for d in xml.iter("{*}FRBRWork"):
            for el in d.iter("{*}FRBRdate"):
                el.set("date", work_date)
    if title:
        for alias in xml.iter("{*}FRBRalias"):
            if alias.get("name") == "title":
                alias.set("value", title)
    return xml


def to_akn(text: str, frbr_uri: str, root: str = "act", expression_date: str | None = None,
           title: str | None = None, work_date: str | None = None) -> bytes:
    """The Akoma Ntoso XML of one Bluebell text; the arguments are those of ``to_akn_tree``."""
    return _xml_bytes(to_akn_tree(text, frbr_uri, root, expression_date, title, work_date))


def _xml_bytes(xml) -> bytes:
    from lxml import etree

    return etree.tostring(xml, encoding="utf-8", pretty_print=True, xml_declaration=True)


def _lampiran_eids(text: str) -> tuple[str, ...]:
    """The eId prefixes ("att_2__") of the text's Lampiran attachments: attachments are
    numbered in the order of their ``ATTACHMENT`` lines."""
    import re

    heads = re.findall(r"^ATTACHMENT (.*)$", text, re.MULTILINE)
    return tuple(f"att_{n}__" for n, head in enumerate(heads, start=1)
                 if head.lower().startswith("lampiran"))


def _check_no_leaked_markup(xml, lampiran: tuple[str, ...] = ()) -> None:
    import re

    from .bluebell import KEYWORDS

    # markup shows as a keyword then a space or the end ("ART 1 -", "POINT (a)", "BODY"); a
    # keyword-like word in the law's own text is not ("TR: Tegangan Rendah", UU 59/2024).
    # "PARA" before a word in capitals is the Indonesian plural, while markup's PARA comes
    # before its number ("PARA (1)", "PARA Ayat (1)") (2026-11-28: UU 2/2023, "PARA PEJABAT
    # BERWENANG"). A Lampiran keeps its printed lines (rule S23), so a treaty's own "ARTICLE 9"
    # or "PART I" there is text (2026-11-28: UU 15/2009 kept its old text over it)
    keywords = "|".join(sorted(KEYWORDS, key=len, reverse=True))
    leaked = re.compile(rf"^(?!PARA [A-Z]{{2,}}\b)(?:{keywords})(?:\s|$)")
    for p in xml.iter("{*}p"):
        text = "".join(p.itertext()).strip()
        if leaked.match(text) and not (p.get("eId") or "").startswith(lampiran):
            raise LeakedMarkupError(f"{p.get('eId')}: markup in text: {text[:80]!r}")


def ruu_frbr_uri(slug: str, doc_date: str) -> str:
    """A bill has no number until enacted: /akn/id/bill/<year>/<slug>."""
    return f"/akn/id/bill/{doc_date[:4]}/{slug}"


def ruu_akn_args(slug: str, rec: dict, doc: dict) -> dict:
    """The arguments of ``to_akn`` and ``to_akn_tree`` (after the text) for one RUU version."""
    date = str(doc["date"])
    full_date = date if len(date) == 10 else None
    return {"frbr_uri": ruu_frbr_uri(slug, date), "root": "bill", "expression_date": full_date,
            "title": doc.get("ruu_title") or rec["title"], "work_date": full_date}


def build_ruu(data_dir: Path, out_dir: Path) -> list[Path]:
    """Generate Akoma Ntoso XML for every RUU version that has text."""
    written = []
    for record in sorted((data_dir / "ruu").glob("*/ruu.yaml")):
        slug = record.parent.name
        rec = load_yaml(record.read_text())
        for doc in rec.get("documents", []):
            if not doc.get("text"):
                continue
            text = (record.parent / doc["text"]).read_text()
            xml = to_akn(text, **ruu_akn_args(slug, rec, doc))
            target = out_dir / "ruu" / slug / f"{doc['id']}.xml"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(xml)
            written.append(target)
    return written


@dataclass(frozen=True)
class _Job:
    """One text version of a law to write as Akoma Ntoso."""
    record: Path
    target: Path
    law: LawContext


def _build_version(job: _Job) -> Path | None:
    rec, version = job.law.rec, job.law.version
    text = job.record.parent / version["text"]
    newest = max(text.stat().st_mtime, job.record.stat().st_mtime)
    if job.target.exists() and job.target.stat().st_mtime >= newest:
        return job.target                                # up to date
    date = version.get("date")
    full = date if date and len(date) == 10 else None
    try:
        xml = to_akn_tree(text.read_text(), rec["akn"], "act", expression_date=full,
                          title=rec.get("title"), work_date=rec.get("tanggal_penetapan") or full)
    except Exception as e:  # noqa: BLE001 - one bad text must not stop the site build
        print(f"skip {text.name}: {type(e).__name__}: {str(e)[:120]}")
        return None
    add_context(xml, job.law)
    job.target.parent.mkdir(parents=True, exist_ok=True)
    job.target.write_bytes(_xml_bytes(xml))
    return job.target


def _short_names(data_dir: Path) -> dict[str, str]:
    """The common short name ("UU ITE") of each law that has one: the base of a named
    collection in data/koleksi/."""
    names = (load_yaml(f.read_text()) for f in sorted((data_dir / "koleksi").glob("*.yaml")))
    return {k["base"]: k["name"] for k in names}


def build_peraturan(data_dir: Path, out_dir: Path) -> list[Path]:
    """Generate Akoma Ntoso XML for every regulation text version (in parallel; unchanged
    texts are skipped)."""
    from concurrent.futures import ProcessPoolExecutor

    records = {path: load_record(path)
               for path in sorted((data_dir / "peraturan").glob("*/*/*/*.yaml"))}
    took = {rec["id"]: took_effect(rec)[0] for rec in records.values()}
    short_names = _short_names(data_dir)
    jobs = []
    for record, rec in records.items():
        revoked_on = {law: took[law] for law in rec["relationships"]["revoked_by"]
                      if len(took.get(law) or "") == 10}
        rel = record.parent.relative_to(data_dir / "peraturan")
        jobs += [_Job(record, out_dir / "peraturan" / rel / f"{v['id']}.xml",
                      LawContext(rec, v, short_names.get(rec["id"]), revoked_on))
                 for v in rec.get("versions") or [] if v.get("text")]
    with ProcessPoolExecutor() as pool:
        return [t for t in pool.map(_build_version, jobs, chunksize=16) if t]
