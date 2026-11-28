"""The shape of a law record, ``data/peraturan/<jenis>/<tahun>/<id>/<id>.yaml``.

Records stay plain dicts (every importer works on them that way). The models here are the
gate: ``save_record`` refuses a record with an unknown key or a value of the wrong type
before anything is written, and ``load_record`` refuses one that is already malformed. The
file is dumped from the same dict, never from a model, so the YAML is exactly what the code
wrote before the schema existed (``allow_unicode=True, sort_keys=False``).

Derived from the 1,930 records in ``data/`` and from the code that writes them
(``sources/peraturan_bpk.py``, ``sources/peraturan_go_id.py``, ``relations.py``,
``history.py``, ``uploads.py``). A new key goes in here first, then in the code that writes it.
"""
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .yamlio import load_yaml

# YYYY-MM-DD, as a string (yaml.safe_dump quotes it, so it loads back as a string)
Date = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class _Model(BaseModel):
    # strict: "5" is not an int, 5 is not a str; extra: a misspelt key is an error
    model_config = ConfigDict(extra="forbid", strict=True)


class StatusRef(_Model):
    """One law named on BPK's detail page under a heading of STATUS (Mengubah, Dicabut dengan …).
    ``id``, ``tentang`` and ``url`` are None for a citation BPK does not link."""
    id: str | None
    citation: str
    tentang: str | None
    url: str | None
    note: str | None


class UjiMateri(_Model):
    """A Constitutional Court / Supreme Court ruling on the law, from BPK's page."""
    putusan: str
    url: str
    amar: str | None


class OtherSource(_Model):
    """Where the record came from before BPK became the primary source."""
    source_url: str | None
    source_pdf_url: str | None


class BpkFile(_Model):
    """A PDF BPK lists for the law. The first three are written when the page is read; the
    rest once the file is downloaded."""
    url: str
    bpk_file_id: int
    filename: str
    sha256: str | None = None
    bytes: int | None = None
    archive_url: str | None = None       # our archive.org copy (existing data only; nothing is uploaded any more)
    archived_sha256: str | None = None   # archive.org's copy differs (repaired PDF; existing data)
    archive_refused: str | None = None   # archive.org refused the file; reason (existing data)
    fetched_from: str | None = None      # the bytes came from a mirror, not BPK; note naming it


class SkippedFile(_Model):
    bpk_file_id: int
    reason: str                # a copy of another file, another law, …


class FileOrder(_Model):
    """The order in which a law's BPK files are joined and parsed, chosen by the agent routine
    (decisions 0022, 0023). Its answer file, data/queue-answers/file-order/<id>.yaml, has the
    same shape. Each file of the law is in ``order`` or in ``skip``, once."""
    order: Annotated[list[int], Field(min_length=1)]   # bpk_file_id, read first to last
    skip: list[SkippedFile]
    reason: str                # one line


class Bpk(_Model):
    """What peraturan.bpk.go.id says about the law."""
    id: int
    files: list[BpkFile]
    status_peraturan: dict[str, list[StatusRef]] | None = None
    tanggal_pengundangan: Date | None = None   # BPK's date when the printed one differs
    no_pdf_checked: Date | None = None         # BPK listed no PDF when last looked at
    file_order: FileOrder | None = None        # written by `hukum-rapih apply-answers`
    # written by the first BPK import (v1-v3); nothing writes them now
    pasal_count: int | None = None
    parser_version: int | None = None


class Changes(_Model):
    """Pasal an amending law changes, inserts or deletes (numbers as printed: "27A")."""
    diubah: list[str] | None = None
    disisipkan: list[str] | None = None
    dihapus: list[str] | None = None


class Amends(_Model):
    id: str
    order: int | None = None   # "Perubahan Kedua" -> 2
    changes: Changes | None = None


class Relationships(_Model):
    amends: list[Amends]
    amended_by: list[str]
    revokes: list[str]
    revoked_by: list[str]
    enacts: list[str] = []      # the first importers wrote only the four above
    enacted_by: list[str] = []
    # a regulation brought back into force, and one whose force ended without a revocation
    # (Keppres 150/1959: the UUD 1945 applies again, the UUDS 1950 no more; decision 0027)
    reinstates: list[str] = []
    reinstated_by: list[str] = []
    ends: list[str] = []
    ended_by: list[str] = []


class FailedCheck(_Model):
    name: str                  # a row of CHECKS in checks.py
    detail: str


class Checks(_Model):
    """The self-checks on a version's text when it was written (checks.py, decision 0026)."""
    version: int                            # CHECKS_VERSION they ran under
    failed: list[FailedCheck]
    word_coverage: float | None = None      # share of the PDF's words in the text
    ocr_unknown_rate: float | None = None   # words the OCR spell fix left unknown, per word


class Version(_Model):
    """One text version of the law, ``<id>.txt`` next to the record."""
    id: str
    kind: str                  # asli
    source: str                # official
    date: Date | None
    date_basis: str            # tanggal_penetapan
    text: str
    pasal_count: int
    parser_version: int | None = None   # texts of the first importer carry no parser data
    pdf_source: str | None = None
    pdf_sha256: str | None = None
    extra_pdf_sha256: list[str] | None = None
    ocr: bool | None = None
    ocr_engine: str | None = None
    ocr_fixed: int | None = None
    ocr_unknown: int | None = None
    checks: Checks | None = None   # texts written before the checks carry none


class AsliPoint(_Model):
    """A point in a law's history that is a stored text version: the law as enacted."""
    id: str
    kind: Literal["asli"]
    date: str                  # a full date, or a bare year when the record knows no more
    date_basis: str            # the record field that gave the date, or "year"
    text: str | None = None    # the version's .txt file; absent when we hold no text


class NotApplied(_Model):
    """An instruction of an amending law that was not split into pasal changes."""
    by: str
    instruction: int | None    # its number in Pasal I; None when the text could not be read
    header: str
    affects_wording: bool      # False for headings and the Penjelasan


class Counts(_Model):
    diubah: int
    disisipkan: int
    dihapus: int


class GabunganPoint(_Model):
    """A point merged by us: the text before it plus the amending law(s) in ``after``.
    Never stored as text; the website builds it (decision 0010)."""
    id: str
    kind: Literal["gabungan"]
    date: str | None           # None when the amending law is not in data/
    date_basis: str | None
    after: list[str]
    order: int                 # "Perubahan Pertama" -> 1
    counts: Counts
    missing_before: int        # earlier amendments we do not have
    unreadable: list[str]      # pasal whose new wording could not be read, so far
    not_applied: list[NotApplied]
    complete: bool             # every pasal's wording is known at this point


class Change(_Model):
    """One change to one pasal by one instruction of an amending law."""
    pasal: str
    type: Literal["diubah", "disisipkan", "dihapus"]
    by: str
    instruction: int | None
    point: str
    wording: Literal["read", "unreadable", "none"]


class History(_Model):
    """The versions of an amended law and every change to it (``history.py``, decision 0010)."""
    points: list[Annotated[AsliPoint | GabunganPoint, Field(discriminator="kind")]]
    changes: list[Change]


class Record(_Model):
    # --- identity (every writer sets these) ---
    id: str
    akn: str
    type: str
    number: str | None         # None only for the UUD 1945, which has no number
    year: int
    title: str
    tentang: str | None
    short_name: str | None     # always None: short names live in data/koleksi/
    status: str | None
    tanggal_penetapan: Date | None
    tempat_penetapan: str | None
    pejabat_penetapan: str | None
    pemrakarsa: str | None
    source_url: str | None
    source_pdf_url: str | None
    relationships: Relationships
    versions: list[Version]
    # --- added by BPK's detail page ---
    lembaran_negara: str | None = None
    subjek: str | None = None
    tanggal_pengundangan: Date | None = None
    tanggal_berlaku: Date | None = None
    tanggal_penetapan_bpk: Date | None = None   # BPK's date when it differs from ours
    uji_materi: list[UjiMateri] | None = None
    bpk: Bpk | None = None
    other_sources: list[OtherSource] | None = None
    # --- written by history.py, only for a law that has been amended ---
    history: History | None = None
    # --- conversion state ---
    pdf_sha256: str | None = None
    pdf_quality: str | None = None
    parse_error: str | None = None
    reparse_error: str | None = None
    recheck: str | None = None
    parser_version_tried: int | None = None


def validate_record(rec: dict) -> dict:
    """Raise ``pydantic.ValidationError`` if ``rec`` is not a well-formed law record;
    return ``rec`` itself, untouched."""
    Record.model_validate(rec)
    return rec


def dump_record(rec: dict) -> str:
    """The YAML text of a record, validated first."""
    validate_record(rec)
    return yaml.safe_dump(rec, allow_unicode=True, sort_keys=False)


def load_record(path: Path) -> dict:
    """Read a record file as a dict; raises if it does not fit the schema."""
    try:
        return validate_record(load_yaml(Path(path).read_text()))
    except ValueError as e:                  # pydantic.ValidationError is a ValueError
        raise ValueError(f"{path}: {e}") from e


def save_record(path: Path, rec: dict) -> None:
    """Validate ``rec`` and write it to ``path``. Nothing is written when it is malformed."""
    try:
        text = dump_record(rec)
    except ValueError as e:
        raise ValueError(f"{path}: {e}") from e
    Path(path).write_text(text)
