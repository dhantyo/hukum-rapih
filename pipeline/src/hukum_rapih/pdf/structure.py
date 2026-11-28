"""Cleaned lines of an Indonesian regulation or draft -> a flat list of structural blocks
(BAB, Bagian, Paragraf, Pasal, ayat, list items, Penjelasan), written out by ``akn/bluebell.py``.

Structure markers are only accepted in sequence (Pasal n+1 after Pasal n, ayat (k+1) after (k),
b after a, ...). That keeps cross-references that happen to start a wrapped line ("Pasal 5 ayat
(1) ...") from being mistaken for headings. What each line is on its own comes from the line
registry (``lines.py``); this module decides what it means given what came before, with a state
machine: ``TABLE`` gives each ``State`` its cells, tried in order (docs/parser-rules.md,
"Structure", names the rule each cell carries out).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import accumulate
from pathlib import Path

from .lines import Kind, Line, classify, normalise
from .ocr_fix import Fixes

PARSER_VERSION = 20  # 20: a joined file (decision 0023) with no Penjelasan or Lampiran heading of its own starts a Lampiran once the law's own text has ended, and a copy certification ends with its file; "PARA PEJABAT" in a text is no longer taken for leaked markup (2026-11-28: UU 13/2014 and 17 other ratification laws had the treaty, a file of its own, as Penjelasan or closing text; UU 2/2023). 19: a treaty's ARTICLE or PART line printed in a Lampiran no longer fails the AKN leak check (2026-11-28: UU 15/2009, UU 21/2009, UU 26/2014 kept their old text). 18: in a Lampiran, only a Penjelasan heading naming the law itself opens its Penjelasan; an enacted Perppu's stays in the Lampiran (2026-11-27: UU 9/2017 had the Perppu's heading for its Penjelasan, its own lost in the Lampiran). 17: a heading after "… berbunyi sebagai berikut:" is the amended law's quoted pasal, never a skipped or misprinted number of the law's own (UU 7/2021 lost Pasal 5 and 8). 16: page header and footer of scanned pages removed by where the OCR put them, not by their (misread) text (pdf/edges.py). 15: misread words of scanned pages corrected when the spell check is confident (pdf/ocr_fix.py, decision 0013). 14: scanned pages read with Indra OCR instead of Tesseract (decision 0012; parser unchanged). 13: misprinted pasal numbers confirmed by the next heading ("Pasal 9" twice, UU 19/1948). 12: OCR letters for digits in heading numbers ("Pasal S1"), spaced marks ("Pasal 84 ,"); amending Penjelasan: Angka above Ayat (UU 11, 12, 13/2022). 11: OCR specks after a Pasal heading ("Pasal 4 :", UU 29/2024); parallel OCR (same words). 10: OCR speck before a Pasal heading ("' Pasal 8", UU 135/2024). 9: browser print headers/footers dropped; separate Penjelasan PDF read (UU 19/2003). 8: v7 dropped a Penjelasan after a copy certification (UU 2/2025): fixed;
#                    Penjelasan of amending laws (Pasal I/II), OCR '1. UMUM'.
#                   7: amending laws keep quoted articles in Pasal I, white (hidden)
#                    text dropped, salinan certification left out, MEMORI PENJELASAN;
#                   6: scanned pages read with our own OCR (Tesseract ind), page-turn words
#                    anywhere on a page;
#                   5: printed lines rebuilt from word positions, page-turn words, headings
#                    with a full stop ("Pasal 1."), old numbering, closing line by line;
#                   2: page headers/numbers on every page (Pasal.id rules); 3: old-spelling closings and
#                    PENDJELASAN; 4: lists between a BAB heading and its first Pasal (UU 19/2003)
# Texts made by a parser older than this are re-converted on the next import; newer ones only
# when the record is flagged (kept old text, parse error, no text). Raise it only for a fix
# that changes laws which pass every check (2026-11-22: don't redo good work). 17: the
# self-check gate (decision 0026) keeps a redone text only when no check gets worse, so the
# v11 to v16 texts (about 1,900 on 2026-11-28, most v12) get v13 to v17's fixes.
PARSER_REDO_BELOW = 17
# Same, for texts read with OCR (scanned pages) only: a fix that changes only scanned pages
# redoes the ~330 OCR'd laws without the ~1,600 typed ones. 16: page header/footer by
# position (2026-11-24: UU 100/2024 kept "RESIDEN REPUBlK INDONESIA" in its title). 18: the
# gate, as for PARSER_REDO_BELOW (2026-11-28).
OCR_REDO_BELOW = 18

ORDINAL = {"PERTAMA": 1, "KESATU": 1, "KEDUA": 2, "KETIGA": 3, "KEEMPAT": 4, "KELIMA": 5,
           "KEENAM": 6, "KETUJUH": 7, "KEDELAPAN": 8, "KESEMBILAN": 9, "KESEPULUH": 10}
SALINAN_MAX = 15  # lines of a copy's certification block ("Salinan sesuai dengan aslinya" …)
NEXT_HEADING_WITHIN = 400  # lines, the heading itself included, a misprint check reads for the next Pasal (S3)
PENJELASAN_TITLE_LINES = 6  # lines after a Penjelasan heading that may hold the law it names (S23)
# lines at the start of a joined file that may hold its Penjelasan or Lampiran heading, after a
# crest caption or the TLN's own header (S34; UU 2/2016's header is 6 lines)
FILE_HEAD_LINES = 10
# a law cited in capitals, a Perppu marked: "PENGGANTI UNDANG-UNDANG REPUBLIK INDONESIA NOMOR 1 TAHUN 2017"
CITED_RE = re.compile(r"\b(PENGGANTI\s+)?UNDANG-\s?UNDANG\b[A-Z ]*?\b(?:NOMOR|NO\.|No\.)\s*(\d+)\s+TAHUN\s+(\d{4})")
# the block a Penjelasan part line (Kind.PENJELASAN_PART) opens, and its text
PENJELASAN_PARTS = {"umum": "Umum", "pasal_demi_pasal": "Pasal demi Pasal"}


@dataclass
class Block:
    kind: str           # title, preamble, bab, bagian, paragraf, pasal, ayat, item, text,
    #                     penjelasan, umum, pasal_demi_pasal, p_pasal, p_label
    label: str = ""
    text: str = ""
    level: int = 0      # list nesting for items


@dataclass
class Document:
    blocks: list[Block] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ocr_fixes: Fixes | None = None      # misread words corrected / left as read (pdf/ocr_fix.py)

    @property
    def pasal_count(self) -> int:
        return sum(1 for b in self.blocks if b.kind == "pasal")

    @property
    def amending(self) -> bool:
        """An amending law: its own articles are Pasal I, II … (the quoted new wording sits
        inside Pasal I)."""
        first = next((b.label for b in self.blocks if b.kind == "pasal"), "")
        return bool(re.search(r"\b[IVX]+\s*\.?$", first))

    @property
    def bab_count(self) -> int:
        return sum(1 for b in self.blocks if b.kind == "bab")


def join(a: str, b: str) -> str:
    if not a:
        return b
    if not b:
        return a
    if re.search(r"[A-Za-z]-$", a):           # Undang-\nUndang
        return a + b
    return f"{a} {b}"


def tidy(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(\w)- (\w)", r"\1-\2", text)   # "Undang- Undang" from justified layout
    text = re.sub(r"\s+([,;:.)])", r"\1", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"([“‘])\s+", r"\1", text)
    text = re.sub(r"\s+([”’])", r"\1", text)
    text = re.sub(r"^:\s*", "", text)
    return text


def roman(s: str) -> int:
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    total = 0
    for i, ch in enumerate(s):
        v = vals[ch]
        total += -v if i + 1 < len(s) and vals[s[i + 1]] > v else v
    return total


def _follows(last: str, marker: str, kind: str) -> bool:
    if kind == "letter":
        return len(marker) == 1 and ord(marker) == ord(last) + 1
    return int(marker) == int(last) + 1


def is_caps(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


# --------------------------------------------------------------------------- structure


def is_heading(line: Line) -> bool:
    return Kind.PASAL in line or Kind.BAGIAN in line or Kind.PARAGRAF in line


def heading_number(label: str) -> int:
    return ORDINAL[label.upper()] if label.upper() in ORDINAL else roman(label.upper())


def pasal_number(num: str) -> int:
    return int(re.match(r"\d+", num)[0]) if num[0].isdigit() else roman(num)


# --------------------------------------------------------------------------- the machine
#
# Structure is a state machine over classified lines. TABLE maps each State to its cells in the
# order they are tried: the first cell whose line class the line has and whose guard holds acts
# on the line. Counters live in Context and are read by guards; look-ahead guards read a View.


class State(StrEnum):
    FRONT = "front"                         # the title, before any preamble line or heading
    PREAMBLE = "preamble"                   # Menimbang … Menetapkan, and headings before Pasal 1
    BODY = "body"
    AMENDING = "amending"                   # an amending law's Pasal I, II: quoted wording is text
    CLOSING = "closing"                     # Disahkan … LN lines, over the part it closes
    SALINAN = "salinan"                     # the copy's certification, left out, over a part
    PENJELASAN_UMUM = "penjelasan_umum"     # the Penjelasan before its first pasal
    PENJELASAN_PASAL = "penjelasan_pasal"   # Pasal demi Pasal
    PENJELASAN_PASAL_I = "penjelasan_pasal_i"   # Pasal demi Pasal of an amending law: Pasal I, II
    LAMPIRAN = "lampiran"


# CLOSING and SALINAN lie over a part of the document and give way to it (``settle``)
OVER = frozenset({State.CLOSING, State.SALINAN})

Lists = tuple[tuple[str, str], ...]


@dataclass
class Context:
    """The document so far and the counters the guards read. Only cell actions change it."""

    doc: Document = field(default_factory=Document)
    state: State = State.FRONT
    part: State = State.FRONT       # the last state that is not OVER: where CLOSING and SALINAN return
    last_pasal: int = 0
    last_bab: int = 0
    last_ayat: int = 0
    # open lists inside the current ayat or pasal, outermost first: (kind, last marker); letters
    # inside a numbered item (or numbers inside a lettered one) nest one deeper
    lists: Lists = ()
    p_last_pasal: int = 0           # the Penjelasan's last pasal
    quoted_one: bool = False        # Pasal I has quoted the amended law's Pasal 1 (S29)
    amending_law: bool = False      # the body was AMENDING when the Penjelasan opened (S21)
    salinan_lines: int = 0          # lines of the certification left out so far (S25)

    @property
    def cur(self) -> Block | None:
        return self.doc.blocks[-1] if self.doc.blocks else None

    def enter(self, state: State) -> None:
        self.state = state
        if state not in OVER:
            self.part = state


@dataclass(frozen=True)
class View:
    """The line being read, with read-only access to the lines before and after it."""

    lines: Sequence[Line]
    at: int
    starts: frozenset[int] = frozenset()    # first line of each joined file after the first (S34)

    @property
    def before(self) -> str:
        return self.lines[self.at - 1].text if self.at else ""

    def ahead(self, n: int) -> Sequence[Line]:
        return self.lines[self.at + 1:self.at + 1 + n]


Guard = Callable[[Context, Line, View], bool]
Action = Callable[[Context, Line, View], int]     # lines used; 0: read the line again in the next state


@dataclass(frozen=True)
class Cell:
    name: str
    ids: tuple[str, ...]            # the rules of docs/parser-rules.md this cell carries out
    kind: Kind | None               # the line class it reads; None: any line
    guard: Guard
    action: Action
    then: State | Callable[[Context], State] | None = None    # next state; None: stay


@dataclass(frozen=True)
class Trace:
    """One cell's reading of one line, as ``step`` reports it to an observer (``hukum-rapih
    explain``). ``used`` 0: the cell read the line again in ``after``, which reports it once more."""

    at: int                 # index of the line in the normalised lines
    line: Line
    before: State
    cell: Cell
    after: State
    used: int


Observer = Callable[[Trace], None]


def ignore(trace: Trace) -> None:
    """The default observer: parsing does not depend on who watches."""


def step(ctx: Context, view: View, observe: Observer = ignore) -> int:
    line, before = view.lines[view.at], ctx.state
    for cell in TABLE[before]:
        if (cell.kind is None or cell.kind in line) and cell.guard(ctx, line, view):
            used = cell.action(ctx, line, view)
            then = cell.then(ctx) if callable(cell.then) else cell.then
            if then is not None:
                ctx.enter(then)
            observe(Trace(view.at, line, before, cell, ctx.state, used))
            return used or step(ctx, view, observe)
    raise AssertionError(f"no cell of {ctx.state} reads {line.text!r}")


# --------------------------------------------------------------------------- actions' tools


def emit(ctx: Context, block: Block) -> None:
    ctx.doc.blocks.append(block)


def append(ctx: Context, text: str) -> None:
    """The line continues the open block (S11); after a heading it starts a text block."""
    cur = ctx.cur
    if cur is None or cur.kind in {"bab", "bagian", "paragraf", "pasal", "p_pasal"}:
        emit(ctx, Block("text", text=text))
    else:
        cur.text = join(cur.text, text)


def place(lists: Lists, kind: str, marker: str) -> tuple[int, Lists] | None:
    """Nesting level (1 = outermost) and the open lists after ``marker`` if it can start or
    continue a list here, else None (S9, S10). ``kind`` is "letter" (a., b., ...) or "number"."""
    for depth in range(len(lists) - 1, -1, -1):          # continue an open list
        open_kind, last = lists[depth]
        if open_kind == kind and _follows(last, marker, kind):
            return depth + 1, (*lists[:depth], (kind, marker))
    if marker != ("a" if kind == "letter" else "1"):
        return None
    if lists and lists[-1][0] != kind:                   # nested list under an item
        return len(lists) + 1, (*lists, (kind, marker))
    return 1, ((kind, marker),)                          # new list at the top


# --------------------------------------------------------------------------- look-ahead guards


def take_title(view: View, caps: bool) -> tuple[str, int]:
    """A heading's title on the next line(s) (S6, S7), and the lines it and its heading use."""
    lines, i = view.lines, view.at
    parts, j = [], i + 1
    while j < len(lines):
        nxt = lines[j]
        if Kind.BAB in nxt or is_heading(nxt):
            break
        if caps and not is_caps(nxt.text):
            # older laws: the title in normal capitals, over up to four short lines
            # ("Tentang Urusan Rumah-Tangga" / "dan Kewajiban-Kewajiban" …), then a heading
            if j == i + 1 and nxt.text[:1].isupper():
                k = j
                while (k < len(lines) and k - j < 4 and len(lines[k].text.split()) <= 12
                       and not lines[k].text.endswith(":") and not is_heading(lines[k])
                       and not re.match(r"^[IVXLC]+\.\s", lines[k].text)):
                    k += 1
                if k < len(lines) and (is_heading(lines[k]) or re.match(r"^[IVXLC]+\.\s", lines[k].text)):
                    parts.extend(ln.text for ln in lines[j:k])
                    j = k
            break
        parts.append(nxt.text)
        j += 1
        if not caps:
            break
    return " ".join(parts), j - i


def title_follows(view: View) -> bool:
    """A capitals line follows that is not a Pasal heading (S5)."""
    return any(is_caps(ln.text) and Kind.PASAL not in ln for ln in view.ahead(1))


def next_heading(view: View) -> int | None:
    """Number of the next line that is a whole 'Pasal N' heading, within NEXT_HEADING_WITHIN
    lines (S3)."""
    for ln in view.ahead(NEXT_HEADING_WITHIN - 1):
        if (pasal := ln.get(Kind.PASAL)) and not pasal[0][-1].isalpha():
            return int(pasal[0]) if pasal[0].isdigit() else roman(pasal[0])
        if Kind.PENJELASAN in ln or Kind.CLOSING in ln:
            return None
    return None


def after_sentence(view: View) -> bool:
    """The line before ends a sentence or is a heading ("Cukup jelas" ends without a stop)."""
    prev = view.before.rstrip()
    return (prev.endswith((".", ";", ":", ")")) or is_caps(prev) or Kind.PASAL in classify(prev)
            or prev.lower().endswith("cukup jelas"))


def quote_follows(view: View) -> bool:
    """The line before leads into quoted text ("… sehingga berbunyi sebagai berikut:"): the
    heading is the amended law's own, quoted in an amending law (S4, UU 7/2021, Arabic pasal)."""
    return bool(re.search(r"berikut\s*:\s*$", view.before, re.IGNORECASE))


def misprinted(view: View, n: int, last: int) -> bool:
    """A heading whose printed number breaks the sequence but the next heading continues it
    (S3): a misprint in the copy ('Pasal 9' twice, UU 19/1948; 'Pasal 8' for 3, UU 29/1948;
    'Pasal II' for 11, UU 1/1951), or a number the copy skips (the next is one more than this).
    It must follow the end of a sentence, so a cross-reference wrapped onto its own line is not
    taken."""
    if not after_sentence(view) or quote_follows(view):
        return False
    nxt = next_heading(view)
    return nxt == last + 2 or (last + 1 < n <= last + 3 and nxt == n + 1)


def amends_so_far(doc: Document) -> bool:
    """Pasal I so far contains amendment wording (S28)."""
    k = max(i for i, b in enumerate(doc.blocks) if b.kind == "pasal")
    text = " ".join(b.text for b in doc.blocks[k:])
    return bool(re.search(r"diubah|disisipkan|dihapus|ditambah|sebagai berikut|berbunyi", text))


def reads_as_amending(doc: Document, view: View) -> bool:
    """The title says PERUBAHAN and 'Beberapa ketentuan … diubah' follows (S30)."""
    title = " ".join(b.text for b in doc.blocks if b.kind == "title").upper()
    nxt = " ".join(ln.text for ln in view.ahead(2))
    return "PERUBAHAN" in title and bool(re.match(
        r"^(Beberapa ketentuan|Ketentuan .{0,80}diubah|Undang-Undang Nomor .{0,200}diubah)", nxt))


def had_penjelasan(doc: Document) -> bool:
    return any(b.kind == "penjelasan" for b in doc.blocks)


# --------------------------------------------------------------------------- guards and actions


def always(ctx: Context, line: Line, view: View) -> bool:
    return True


def no_block_yet(ctx: Context, line: Line, view: View) -> bool:
    return ctx.cur is None


def in_bab(ctx: Context, line: Line, view: View) -> bool:
    return bool(ctx.last_bab)


def take_text(ctx: Context, line: Line, view: View) -> int:
    append(ctx, line.text)
    return 1


def emit_item(ctx: Context, item: tuple, level: int) -> None:
    emit(ctx, Block("item", label=f"{item[1]}.", text=item[2], level=level))


def place_item(ctx: Context, item: tuple) -> int | None:
    """Place a list item and keep the lists it opens; its level, None if it cannot be placed."""
    if placed := place(ctx.lists, item[0], item[1]):
        ctx.lists = placed[1]
        return placed[0]
    return None


def bab_follows(ctx: Context, line: Line, view: View) -> bool:
    n = heading_number(line.get(Kind.BAB)[0])
    return n == ctx.last_bab + 1 or (n == ctx.last_bab and title_follows(view))


def take_bab(ctx: Context, line: Line, view: View) -> int:
    label = line.get(Kind.BAB)[0]
    n = heading_number(label)
    ctx.last_bab = n + (n == ctx.last_bab)
    title, used = take_title(view, caps=True)
    emit(ctx, Block("bab", label=f"BAB {label}", text=title))
    return used


def take_bagian(ctx: Context, line: Line, view: View) -> int:
    title, used = take_title(view, caps=False)
    emit(ctx, Block("bagian", label=f"Bagian {line.get(Kind.BAGIAN)[0]}", text=title))
    return used


def take_paragraf(ctx: Context, line: Line, view: View) -> int:
    title, used = take_title(view, caps=False)
    emit(ctx, Block("paragraf", label=f"Paragraf {line.get(Kind.PARAGRAF)[0]}", text=title))
    return used


def pasal_follows(ctx: Context, line: Line, view: View) -> bool:
    """The next number, or the same one with a letter (S1, S2); anything else is a
    cross-reference that happens to start a wrapped line."""
    num = line.get(Kind.PASAL)[0]
    n = pasal_number(num)
    return n == ctx.last_pasal + 1 or (num[-1].isalpha() and n == ctx.last_pasal)


def take_pasal(ctx: Context, line: Line, view: View, num: str = "") -> int:
    num = num or line.get(Kind.PASAL)[0]
    n = pasal_number(num)
    if n != ctx.last_pasal + 1 and not (num[-1].isalpha() and n == ctx.last_pasal):
        n = ctx.last_pasal + 1 if next_heading(view) == ctx.last_pasal + 2 else n
        ctx.doc.warnings.append(f"'Pasal {num}' printed where Pasal {n} belongs; kept as printed")
    ctx.last_pasal = n
    emit(ctx, Block("pasal", label=f"Pasal {num}"))
    ctx.last_ayat, ctx.lists = 0, ()
    return 1


def pasal_1_read_as_i(ctx: Context, line: Line, view: View) -> bool:
    return line.get(Kind.PASAL) == ("1",) and reads_as_amending(ctx.doc, view)


def pasal_1_read_as_i_before_bab(ctx: Context, line: Line, view: View) -> bool:
    return not ctx.last_bab and pasal_1_read_as_i(ctx, line, view)


def pasal_1_read_as_i_in_bab(ctx: Context, line: Line, view: View) -> bool:
    return bool(ctx.last_bab) and pasal_1_read_as_i(ctx, line, view)


def take_pasal_1_as_i(ctx: Context, line: Line, view: View) -> int:
    ctx.doc.warnings.append("'Pasal 1' read as 'Pasal I' (amending law, OCR)")
    return take_pasal(ctx, line, view, "I")


def pasal_i_before_bab(ctx: Context, line: Line, view: View) -> bool:
    num = line.get(Kind.PASAL)[0]
    return (not num[0].isdigit() and pasal_number(num) == 1 and not ctx.last_bab
            and pasal_follows(ctx, line, view))


def pasal_follows_or_misprinted(ctx: Context, line: Line, view: View) -> bool:
    return pasal_follows(ctx, line, view) or misprinted(view, pasal_number(line.get(Kind.PASAL)[0]),
                                                        ctx.last_pasal)


def ayat_follows(ctx: Context, line: Line, view: View) -> bool:
    return int(line.get(Kind.AYAT)[0]) == ctx.last_ayat + 1


def take_ayat(ctx: Context, line: Line, view: View) -> int:
    number, text = line.get(Kind.AYAT)
    ctx.last_ayat, ctx.lists = int(number), ()
    emit(ctx, Block("ayat", label=f"({number})", text=text))
    return 1


def item_fits(ctx: Context, line: Line, view: View) -> bool:
    item = line.get(Kind.LIST_ITEM)
    return place(ctx.lists, item[0], item[1]) is not None


def take_item(ctx: Context, line: Line, view: View) -> int:
    item = line.get(Kind.LIST_ITEM)
    emit_item(ctx, item, place_item(ctx, item))
    return 1


def own_pasal_2(ctx: Context, line: Line, view: View) -> bool:
    """``Pasal 2`` after Pasal I is the law's own: "Pasal I." was a misprint for Pasal 1 (no
    amendment wording so far, UU 16/1953), or it follows a finished sentence and no quoted Pasal 1
    (UU 2/1953, 12/1957), where a quoted pasal follows "… berbunyi sebagai berikut:" (S28, S29)."""
    return ctx.last_pasal == 1 and line.get(Kind.PASAL) == ("2",) and (
        not amends_so_far(ctx.doc) or (not ctx.quoted_one and view.before.rstrip().endswith(".")))


def read_again(ctx: Context, line: Line, view: View) -> int:
    return 0


def is_pasal_1(ctx: Context, line: Line, view: View) -> bool:
    return line.get(Kind.PASAL) == ("1",)


def take_quoted_pasal_1(ctx: Context, line: Line, view: View) -> int:
    ctx.quoted_one = True
    return take_text(ctx, line, view)


def quoted_heading(ctx: Context, line: Line, view: View) -> bool:
    """BAB, Bagian, Paragraf and Arabic Pasal inside Pasal I are the amended law's quoted wording."""
    pasal = line.get(Kind.PASAL)
    return (Kind.BAB in line or Kind.BAGIAN in line or Kind.PARAGRAF in line
            or bool(pasal and pasal[0][0].isdigit()))


def penjelasan_to_come(ctx: Context, line: Line, view: View) -> bool:
    return not had_penjelasan(ctx.doc)


def cited(text: str) -> tuple[bool, str, str] | None:
    """(a Perppu, number, year) of the first law cited in capitals in ``text``."""
    m = CITED_RE.search(text)
    return (bool(m[1]), m[2], m[3]) if m else None


def penjelasan_of_the_law(ctx: Context, line: Line, view: View) -> bool:
    """In a Lampiran, a Penjelasan heading that names the law itself: its Penjelasan, read after
    the Lampiran from a separate PDF. Any other is the Penjelasan of what the Lampiran prints
    whole, such as an enacted Perppu (S23, UU 9/2017)."""
    title = ctx.doc.blocks[0].text if ctx.doc.blocks and ctx.doc.blocks[0].kind == "title" else ""
    heading = " ".join([line.text, *(ahead.text for ahead in view.ahead(PENJELASAN_TITLE_LINES))])
    return penjelasan_to_come(ctx, line, view) and cited(title) is not None and cited(heading) == cited(title)


def take_penjelasan_heading(ctx: Context, line: Line, view: View) -> int:
    ctx.amending_law = ctx.part is State.AMENDING
    umum = line.get(Kind.PENJELASAN_UMUM)
    emit(ctx, Block("penjelasan", text=umum[0] if umum else line.text))
    if umum:
        emit(ctx, Block("umum", text="Umum"))
    return 1


def numeral_alone(ctx: Context, line: Line, view: View) -> bool:
    return line.get(Kind.PENJELASAN_PART) == ("",)


def take_part(ctx: Context, line: Line, view: View) -> int:
    part = line.get(Kind.PENJELASAN_PART)[0]
    emit(ctx, Block(part, text=PENJELASAN_PARTS[part]))
    return 1


def pasal_i_of_penjelasan(ctx: Context, line: Line, view: View) -> bool:
    """An amending law's Penjelasan explains Pasal I, Pasal II (S21)."""
    num = line.get(Kind.PASAL)[0]
    return not num[0].isdigit() and ctx.amending_law and roman(num) == ctx.p_last_pasal + 1


def take_p_pasal_i(ctx: Context, line: Line, view: View) -> int:
    num = line.get(Kind.PASAL)[0]
    ctx.p_last_pasal = roman(num)
    emit(ctx, Block("p_pasal", label=f"Pasal {num}"))
    return 1


def p_pasal_follows(ctx: Context, line: Line, view: View) -> bool:
    """The Penjelasan's next pasal, or any later pasal of the law after a sentence end: old
    laws explain only some pasal (UU 2/1962: Pasal 5, then Pasal 12) (S19); or a misprint the
    next heading confirms (S20)."""
    num = line.get(Kind.PASAL)[0]
    n, last = pasal_number(num), ctx.p_last_pasal
    skipped = last < n <= ctx.last_pasal and num[0].isdigit() and after_sentence(view)
    return bool((num[0].isdigit() or last) and (
        n == last + 1 or (num[-1].isalpha() and n == last) or skipped
        or (last and misprinted(view, n, last))))


def take_p_pasal(ctx: Context, line: Line, view: View) -> int:
    num = line.get(Kind.PASAL)[0]
    n, last = pasal_number(num), ctx.p_last_pasal
    if last and n != last + 1 and next_heading(view) == last + 2:
        n = last + 1
    ctx.p_last_pasal = n
    emit(ctx, Block("p_pasal", label=f"Pasal {num}"))
    return 1


def p_part(ctx: Context) -> State:
    """A Penjelasan pasal heading ends the Umum part, unless it was numbered 0 (``Pasal 0A``)."""
    return State.PENJELASAN_PASAL if ctx.p_last_pasal else State.PENJELASAN_UMUM


def take_p_label(ctx: Context, line: Line, view: View) -> int:
    label, text = line.get(Kind.PENJELASAN_LABEL)
    emit(ctx, Block("p_label", label=label, text=text))
    return 1


def after_sentence_end(ctx: Context, line: Line, view: View) -> bool:
    return ctx.cur.kind == "text" and ctx.cur.text.endswith(".") and line.text[:1].isupper()


def after_part_heading(ctx: Context, line: Line, view: View) -> bool:
    return ctx.cur.kind in {"umum", "pasal_demi_pasal"}


def take_paragraph(ctx: Context, line: Line, view: View) -> int:
    emit(ctx, Block("text", text=line.text))
    return 1


def past_front(ctx: Context) -> State:
    """A Pasal heading ends the front, unless it was numbered 0 (``Pasal 0A``)."""
    return State.BODY if ctx.last_pasal else State.PREAMBLE


def take_opening(ctx: Context, line: Line, view: View) -> int:
    emit(ctx, Block("preamble", text=line.text))
    return 1


def take_preamble_label(ctx: Context, line: Line, view: View) -> int:
    label, rest = line.get(Kind.PREAMBLE)
    emit(ctx, Block("preamble", label=label, text=rest))
    ctx.lists = ()
    if (item := classify(rest).get(Kind.LIST_ITEM)) and place_item(ctx, item):
        ctx.cur.text = ""
        emit_item(ctx, item, 1)
    return 1


def skip(ctx: Context, line: Line, view: View) -> int:
    return 1


def take_title_line(ctx: Context, line: Line, view: View) -> int:
    emit(ctx, Block("title", text=line.text))
    return 1


def label_alone(ctx: Context, line: Line, view: View) -> bool:
    return ctx.cur.kind == "preamble" and line.text.startswith(":")


def take_after_label(ctx: Context, line: Line, view: View) -> int:
    """The label alone, ": 1. …" on the next line: the first item, or the text, without the colon."""
    line = classify(line.text.lstrip(": ").strip())
    if not ctx.cur.text and (item := line.get(Kind.LIST_ITEM)) and place_item(ctx, item):
        emit_item(ctx, item, 1)
        return 1
    return take_flat_item(ctx, line, view) if Kind.LIST_ITEM in line else take_text(ctx, line, view)


def in_preamble_list(ctx: Context, line: Line, view: View) -> bool:
    return ctx.cur.kind in {"preamble", "item"}


def take_flat_item(ctx: Context, line: Line, view: View) -> int:
    """Menimbang and Mengingat lists are flat: an item that would nest is text."""
    item = line.get(Kind.LIST_ITEM)
    if place_item(ctx, item) == 1:
        emit_item(ctx, item, 1)
        return 1
    return take_text(ctx, line, view)


def take_closing_line(ctx: Context, line: Line, view: View) -> int:
    emit(ctx, Block("closing", text=line.text))
    return 1


def gives_way(ctx: Context, line: Line, view: View) -> bool:
    """A Penjelasan heading or a draft's ``RANCANGAN`` line under the closing (S17)."""
    return Kind.PENJELASAN in line or line.text == "RANCANGAN"


def read_in_part(ctx: Context, line: Line, view: View) -> int:
    """The line is read by the part the closing lies over (``settle`` decides what is open next)."""
    ctx.enter(ctx.part)
    return step(ctx, view)


def settle(ctx: Context) -> State:
    """Back to the part, or to the closing while the open block is a closing line (S16)."""
    return State.CLOSING if ctx.part is not State.LAMPIRAN and ctx.cur.kind == "closing" else ctx.part


def sentence_goes_on(ctx: Context, line: Line, view: View) -> bool:
    """The ``Agar setiap orang …`` sentence joins until its full stop (S16)."""
    return ctx.cur.text.startswith("Agar") and not ctx.cur.text.rstrip().endswith(".")


def take_lampiran(ctx: Context, line: Line, view: View) -> int:
    emit(ctx, Block("lampiran", label=line.text))
    return 1


def take_lampiran_text(ctx: Context, line: Line, view: View) -> int:
    emit(ctx, Block("lampiran_text", text=line.text))
    return 1


def file_starts(ctx: Context, line: Line, view: View) -> bool:
    return view.at in view.starts


def file_opens_no_part(ctx: Context, line: Line, view: View) -> bool:
    """A joined file starts here with no Penjelasan or Lampiran heading in its first
    FILE_HEAD_LINES lines: it is a Lampiran printed without one, such as the treaty a law
    ratifies (S34, UU 13/2014)."""
    head = (line, *view.ahead(FILE_HEAD_LINES - 1))
    return file_starts(ctx, line, view) and not any(
        Kind.PENJELASAN in ln or Kind.LAMPIRAN in ln for ln in head)


def take_unheaded_lampiran(ctx: Context, line: Line, view: View) -> int:
    """No heading is printed, so the Lampiran is named for its part; the file's first line is
    read again as its text."""
    emit(ctx, Block("lampiran", label="LAMPIRAN"))
    return 0


def take_salinan(ctx: Context, line: Line, view: View) -> int:
    """The copy's certification by the State Secretariat, often under a round stamp: not part of
    the law (and OCR turns the stamp into noise)."""
    ctx.salinan_lines = 0
    ctx.doc.warnings.append("salinan: copy certified ('Salinan sesuai dengan aslinya'); left out")
    return 1


def take_salinan_quietly(ctx: Context, line: Line, view: View) -> int:
    ctx.salinan_lines = 0
    return 1


def salinan_runs_out(ctx: Context, line: Line, view: View) -> bool:
    """The certification is a few lines, so a long skip is a misreading: stop and keep the text
    (UU 2/2025 lost its Penjelasan to this before)."""
    return ctx.salinan_lines >= SALINAN_MAX


def take_salinan_runaway(ctx: Context, line: Line, view: View) -> int:
    ctx.doc.warnings.append(f"salinan: no end found after {SALINAN_MAX} lines; text kept")
    return 0


def salinan_ends(ctx: Context, line: Line, view: View) -> bool:
    return Kind.PENJELASAN in line or Kind.LAMPIRAN in line


def take_salinan_line(ctx: Context, line: Line, view: View) -> int:
    ctx.salinan_lines += 1
    return 1


# --------------------------------------------------------------------------- the cells

BAB_BEFORE_PASAL = Cell("bab_before_pasal", ("S5", "S6"), Kind.BAB, bab_follows, take_bab, State.PREAMBLE)
BAGIAN = Cell("bagian", ("S7",), Kind.BAGIAN, in_bab, take_bagian)
PARAGRAF = Cell("paragraf", ("S7",), Kind.PARAGRAF, in_bab, take_paragraf)
PASAL_I = Cell("pasal_i", ("S26",), Kind.PASAL, pasal_i_before_bab, take_pasal, State.AMENDING)
PASAL_FIRST = (
    Cell("pasal_1_read_as_i", ("S30", "S26"), Kind.PASAL, pasal_1_read_as_i_before_bab, take_pasal_1_as_i,
         State.AMENDING),
    PASAL_I,
    Cell("pasal_first", ("S1", "S2"), Kind.PASAL, pasal_follows, take_pasal, past_front),
)
OPENING = Cell("opening", ("S13",), Kind.OPENING, always, take_opening, State.PREAMBLE)
PREAMBLE_LABEL = Cell("preamble_label", ("S14", "S15"), Kind.PREAMBLE, always, take_preamble_label,
                      State.PREAMBLE)
AYAT = Cell("ayat", ("S8",), Kind.AYAT, ayat_follows, take_ayat)
LIST_ITEM = Cell("list_item", ("S9", "S10", "G3"), Kind.LIST_ITEM, item_fits, take_item)
TEXT = Cell("text", ("S11",), None, always, take_text)
P_PASAL_I = Cell("p_pasal_i", ("S21",), Kind.PASAL, pasal_i_of_penjelasan, take_p_pasal_i,
                 State.PENJELASAN_PASAL_I)
P_PASAL = Cell("p_pasal", ("S19", "S20"), Kind.PASAL, p_pasal_follows, take_p_pasal, p_part)
P_LABEL = Cell("p_label", ("S33",), Kind.PENJELASAN_LABEL, always, take_p_label)
# after the first pasal, before a state's own cells: what ends or interrupts a part
CLOSING_OPENS = Cell("closing_opens", ("S16",), Kind.CLOSING, always, take_closing_line, State.CLOSING)
LAMPIRAN_OPENS = Cell("lampiran_opens", ("S23",), Kind.LAMPIRAN, always, take_lampiran, State.LAMPIRAN)
SALINAN_OPENS = Cell("salinan_opens", ("S24",), Kind.SALINAN, always, take_salinan, State.SALINAN)
OPENERS = (
    Cell("penjelasan_opens", ("S18",), Kind.PENJELASAN, penjelasan_to_come, take_penjelasan_heading,
         State.PENJELASAN_UMUM),
    CLOSING_OPENS, LAMPIRAN_OPENS, SALINAN_OPENS,
)
# a joined file, once the law's own text has ended (its closing read, its Penjelasan open); in
# the body or a Lampiran a file goes on with it (a body or a Lampiran in parts)
FILE_OPENS_LAMPIRAN = Cell("file_opens_lampiran", ("S34",), None, file_opens_no_part, take_unheaded_lampiran,
                           State.LAMPIRAN)


TABLE: dict[State, tuple[Cell, ...]] = {
    State.FRONT: (
        BAB_BEFORE_PASAL, *PASAL_FIRST, OPENING, PREAMBLE_LABEL,
        Cell("crest_caption", ("S13",), Kind.CREST_CAPTION, no_block_yet, skip),
        Cell("title", ("S13",), None, no_block_yet, take_title_line),
        Cell("title_continues", ("S13", "S11"), None, always, take_text),
    ),
    State.PREAMBLE: (
        BAB_BEFORE_PASAL, BAGIAN, PARAGRAF,
        Cell("pasal_1_read_as_i_in_bab", ("S30",), Kind.PASAL, pasal_1_read_as_i_in_bab, take_pasal_1_as_i, State.BODY),
        *PASAL_FIRST, OPENING, PREAMBLE_LABEL,
        Cell("label_alone", ("S14",), None, label_alone, take_after_label),
        Cell("preamble_item", ("S14",), Kind.LIST_ITEM, in_preamble_list, take_flat_item),
        Cell("preamble_text", ("S11",), None, always, take_text),
    ),
    State.BODY: (
        *OPENERS,
        Cell("bab", ("S5", "S6"), Kind.BAB, bab_follows, take_bab), BAGIAN, PARAGRAF, PASAL_I,
        Cell("pasal", ("S1", "S2", "S3", "S4", "G7"), Kind.PASAL, pasal_follows_or_misprinted, take_pasal),
        AYAT, LIST_ITEM, TEXT,
    ),
    State.AMENDING: (
        *OPENERS,
        Cell("own_pasal_2", ("S28", "S29"), Kind.PASAL, own_pasal_2, read_again, State.BODY),
        Cell("quoted_pasal_1", ("S27", "S29"), Kind.PASAL, is_pasal_1, take_quoted_pasal_1),
        Cell("quoted_heading", ("S27",), None, quoted_heading, take_text),
        Cell("pasal_of_amending_law", ("S1", "S26"), Kind.PASAL, pasal_follows, take_pasal),
        AYAT, LIST_ITEM, TEXT,
    ),
    State.CLOSING: (
        FILE_OPENS_LAMPIRAN, *OPENERS,
        Cell("closing_gives_way", ("S17", "G4"), None, gives_way, read_in_part, settle),
        Cell("closing_sentence", ("S16",), None, sentence_goes_on, take_text),
        Cell("closing_line", ("S16",), None, always, take_closing_line),
    ),
    State.SALINAN: (
        Cell("salinan_ends_at_file", ("S34",), None, file_starts, read_again, settle),
        Cell("salinan_runs_out", ("S25",), None, salinan_runs_out, take_salinan_runaway, settle),
        Cell("salinan_ends", ("S25",), None, salinan_ends, read_again, settle),
        Cell("closing_in_salinan", ("S16",), Kind.CLOSING, always, take_closing_line),
        Cell("salinan_line", ("S24",), None, always, take_salinan_line),
    ),
    State.PENJELASAN_UMUM: (
        FILE_OPENS_LAMPIRAN, CLOSING_OPENS, LAMPIRAN_OPENS, SALINAN_OPENS,
        Cell("part_numeral", ("S32",), Kind.PENJELASAN_PART, numeral_alone, skip),
        Cell("part", ("S32",), Kind.PENJELASAN_PART, always, take_part),
        P_PASAL_I, P_PASAL,
        Cell("paragraph", ("S22", "G8"), None, after_sentence_end, take_paragraph),
        Cell("text_after_part", ("S22",), None, after_part_heading, take_paragraph), TEXT,
    ),
    State.PENJELASAN_PASAL: (
        FILE_OPENS_LAMPIRAN, CLOSING_OPENS, LAMPIRAN_OPENS, SALINAN_OPENS, P_PASAL_I, P_PASAL, P_LABEL, TEXT,
    ),
    State.PENJELASAN_PASAL_I: (
        FILE_OPENS_LAMPIRAN, CLOSING_OPENS, LAMPIRAN_OPENS, SALINAN_OPENS, P_PASAL_I, P_LABEL, TEXT,
    ),
    # a Lampiran (maps, tables, schedules, a drafting guide) keeps its lines as printed
    State.LAMPIRAN: (
        Cell("penjelasan_in_lampiran", ("S23",), Kind.PENJELASAN, penjelasan_of_the_law,
             take_penjelasan_heading, State.PENJELASAN_UMUM),
        Cell("closing_in_lampiran", ("G1",), Kind.CLOSING, always, take_closing_line),
        Cell("lampiran_in_lampiran", ("S23", "G2"), Kind.LAMPIRAN, always, take_lampiran),
        Cell("salinan_in_lampiran", ("S24",), Kind.SALINAN, always, take_salinan_quietly, State.SALINAN),
        Cell("lampiran_text", ("S23",), None, always, take_lampiran_text),
    ),
}


def parse_lines(lines: list[str], observe: Observer = ignore) -> Document:
    """The cleaned lines of one file; ``parse_files`` reads several."""
    return parse_files([lines], observe)


def parse_files(files: Sequence[list[str]], observe: Observer = ignore) -> Document:
    """The cleaned lines of each file of a law, read in order as one text (decision 0023). A
    file boundary is a hard break: headings are normalised within their file, and the table
    sees where each file starts (``View.starts``, S34). ``observe`` hears every cell reading of
    every line (``Trace``); it cannot change the result."""
    per_file = [[classify(text) for text in normalise(lines)] for lines in files]
    classified = [line for lines in per_file for line in lines]
    starts = frozenset(accumulate(len(lines) for lines in per_file[:-1]))
    ctx, i = Context(), 0
    while i < len(classified):
        i += step(ctx, View(classified, i, starts), observe)
    for b in ctx.doc.blocks:
        b.text = tidy(b.text)
        b.label = tidy(b.label)
    return ctx.doc


def parse_pdf(pdf: Path, extra: Sequence[Path] = (), stats: dict | None = None) -> Document:
    """``extra``: further PDFs of the same law read after it, such as a Penjelasan that BPK
    publishes as a separate file (UU 19/2003) or a treaty the law ratifies (UU 13/2014).
    ``stats``: filled by the page reading (OCR pages, the header/footer lines cut by position,
    ...) and with the cleaned ``lines`` the parser read, for a caller that wants to see them."""
    from .extract import clean_lines, page_lines

    stats = stats if stats is not None else {}
    files = [clean_lines(page_lines(path, stats), stats) for path in (pdf, *extra)]
    stats["lines"] = [line for lines in files for line in lines]
    doc = parse_files(files)
    if stats.get("ocr_pages"):
        doc.warnings.append(f"ocr: {stats['ocr_pages']} scanned page(s) read with {stats.get('ocr_engine', 'tesseract')}")
    if stats.get("edge_lines"):
        doc.warnings.append(f"edges: {len(stats['edge_lines'])} page header/footer line(s) of scanned pages removed by position")
    if parts := stats.get("ocr_fixes"):
        doc.ocr_fixes = fixes = Fixes(
            [c for f in parts for c in f.changed], [s for f in parts for s in f.suspects],
            "none" if any(f.checker == "none" for f in parts) else "hunspell")
        shown = ", ".join(f"{a}→{b}" for a, b in fixes.changed[:10])
        doc.warnings.append(f"ocr fixes: {len(fixes.changed)} misread word(s) corrected"
                            f"{f' ({shown})' if shown else ''}, {len(fixes.suspects)} unknown word(s) left as read"
                            + ("; Hunspell missing, nothing corrected" if fixes.checker == "none" else ""))
    if stats.get("ocr_fallback"):
        doc.warnings.append(f"ocr fallback, first engine failed: {stats['ocr_fallback']}")
    if stats.get("ocr_missing"):
        doc.warnings.append(f"ocr unavailable, used the PDF's own text layer: {stats['ocr_missing']}")
    return doc
