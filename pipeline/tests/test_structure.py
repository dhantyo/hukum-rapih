import pytest

from hukum_rapih.akn.bluebell import escape, to_bluebell
from hukum_rapih.akn.build import to_akn
from hukum_rapih.pdf.extract import clean_lines
from hukum_rapih.pdf.structure import parse_lines

PAGES = [
    ["F", "PDIP", "PEMERINTAH", "RANCANGAN", "UNDANG-UNDANG REPUBLIK INDONESIA",
     "Menimbang : a.", "bahwa satu;", "b.", "bahwa dua;", "Mengingat", ": Pasal 20 UUD;",
     "MEMUTUSKAN:", "BAB I", "KETENTUAN UMUM", "Pasal 1", "Dalam Undang-", "Undang ini:",
     "1.", "Aset adalah benda.", "2.", "Dokumen adalah:", "a.", "tulisan;", "b.", "peta."],
    ["2", "BAB II", "RUANG", "LINGKUP", "Pasal 2", "(1) Aset dirampas berdasarkan",
     "Pasal 5 ayat (1) huruf a.", "(2) Selain ayat", "(1) tersebut, juga:", "a. benda;",
     "b. hak.", "Agar setiap orang mengetahuinya, memerintahkan.", "Disahkan di Jakarta",
     "PENJELASAN", "I. UMUM", "Ini umum.", "II. PASAL DEMI PASAL", "Pasal 1",
     "Cukup jelas.", "Pasal 2", "Ayat (1)", "Cukup jelas.", "TAMBAHAN LEMBARAN NEGARA"],
]


def parse():
    return parse_lines(clean_lines(PAGES))


def test_headers_and_page_numbers_removed():
    lines = clean_lines(PAGES)
    assert lines[0] == "RANCANGAN"
    assert "2" not in lines and "PDIP" not in lines


def test_structure():
    doc = parse()
    assert doc.pasal_count == 2 and doc.bab_count == 2
    kinds = [(b.kind, b.label) for b in doc.blocks]
    assert ("pasal", "Pasal 1") in kinds and ("p_pasal", "Pasal 2") in kinds
    bab2 = next(b for b in doc.blocks if b.label == "BAB II")
    assert bab2.text == "RUANG LINGKUP"


def test_cross_reference_is_not_a_heading():
    doc = parse()
    ayat = [b for b in doc.blocks if b.kind == "ayat"]
    assert [a.label for a in ayat] == ["(1)", "(2)"]
    assert ayat[0].text == "Aset dirampas berdasarkan Pasal 5 ayat (1) huruf a."
    assert ayat[1].text == "Selain ayat (1) tersebut, juga:"


def test_hyphen_join_and_nesting():
    doc = parse()
    pasal1_text = next(b for b in doc.blocks if b.kind == "text" and "Dalam" in b.text)
    assert pasal1_text.text == "Dalam Undang-Undang ini:"
    items = [(b.label, b.level) for b in doc.blocks if b.kind == "item"]
    assert ("1.", 1) in items and ("a.", 2) in items


NS = {"a": "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"}


def test_bluebell_text():
    text = to_bluebell(parse())
    assert "  CHAPTER II - RUANG LINGKUP\n" in text
    assert "    ART 2 -\n      PARA (1)\n        Aset dirampas berdasarkan Pasal 5" in text
    assert "        POINT a.\n          tulisan;" in text  # nested under POINT 2.
    assert "CONCLUSIONS\n" in text and "ATTACHMENT Penjelasan\n" in text


def test_escape():
    assert escape("dan/atau") == "dan/atau"
    assert escape("lihat https://contoh.go.id") == "lihat https:\\//contoh.go.id"
    assert escape("PART dari aset") == "\\PART dari aset"
    assert escape("a\\b") == "a\\\\b"


def test_akoma_ntoso():
    from lxml import etree

    xml = etree.fromstring(to_akn(to_bluebell(parse()), "/akn/id/bill/2026/contoh", "bill"))
    eids = [e.get("eId") for e in xml.iter() if e.get("eId")]
    assert "chp_I__art_1__point_2__point_a" in eids
    assert "chp_II__art_2__para_2__point_b" in eids
    assert len(xml.findall(".//a:body//a:article", NS)) == 2
    assert len(xml.findall(".//a:attachment//a:article", NS)) == 2
    assert xml.find(".//a:FRBRlanguage", NS).get("language") == "ind"


def test_list_nesting_resets_per_pasal():
    """Regression: letters in a Pasal following a Pasal with numbered definitions were nested
    one level too deep, and Bluebell then showed "POINT a." as text."""
    lines = ["Pasal 1", "Dalam Undang-Undang ini:", "1.", "Aset adalah benda.", "2.",
             "Dokumen adalah:", "a.", "tulisan;", "b.", "peta.",
             "Pasal 2", "Dilaksanakan berdasarkan asas:", "a.", "kepastian hukum", "b.",
             "keadilan;", "c.", "kemanfaatan."]
    doc = parse_lines(lines)
    pasal2 = doc.blocks[[b.label for b in doc.blocks].index("Pasal 2"):]
    assert [(b.label, b.level) for b in pasal2 if b.kind == "item"] == [
        ("a.", 1), ("b.", 1), ("c.", 1)]
    to_akn(to_bluebell(doc), "/akn/id/bill/2026/contoh", "bill")  # raises on leaked markup


def test_numbers_inside_letters_and_back():
    lines = ["Pasal 1", "Meliputi:", "a.", "satu:", "1.", "x;", "2.", "y;", "b.", "dua."]
    items = [(b.label, b.level) for b in parse_lines(lines).blocks if b.kind == "item"]
    assert items == [("a.", 1), ("1.", 2), ("2.", 2), ("b.", 1)]


def test_a_list_starts_only_at_a_or_1():
    # "c." at a line start is a reference wrapped onto the line ("… pada huruf" / "c. …"), not an item
    doc = parse_lines(["Pasal 1", "Ketentuan sebagaimana dimaksud pada huruf", "c. berlaku juga."])
    assert [b.kind for b in doc.blocks] == ["pasal", "text"]


def test_spacing_of_joined_lines_is_tidied():
    doc = parse_lines(["Pasal 1", "Dalam Undang- Undang ini ( satu ) , “ kata ” ."])
    assert doc.blocks[-1].text == "Dalam Undang-Undang ini (satu), “kata”."


@pytest.mark.xfail(strict=True, reason="known gap: list levels a) and 1) (Lampiran II items 94-95) are text")
def test_third_and_fourth_list_levels_are_items():
    doc = parse_lines(["Pasal 1", "(1) Meliputi:", "a. satu:", "1. dua:", "a) tiga:", "1) empat.", "2. lima."])
    assert [(b.label, b.level) for b in doc.blocks if b.kind == "item"] == [
        ("a.", 1), ("1.", 2), ("a)", 3), ("1)", 4), ("2.", 2)]


def test_leaked_markup_is_rejected():
    import pytest

    from hukum_rapih.akn.build import LeakedMarkupError

    bad = "BODY\n  ART 1 -\n    Teks:\n\n      POINT a.\n        x\n"
    with pytest.raises(LeakedMarkupError):
        to_akn(bad, "/akn/id/bill/2026/contoh", "bill")


def test_page_headers_and_numbers_removed_after_page_one():
    """Regression: '-2-' page numbers under a running 'PRESIDEN REPUBLIK INDONESIA' header
    ended up inside the text (peraturan.go.id PDFs)."""
    pages = [
        ["SALINAN", "PRESIDEN", "REPUBLIK INDONESIA", "UNDANG-UNDANG", "Menimbang: a.", "bahwa satu;"],
        ["FRESIDEN", "REPUEUK INDONESIA", "-2-", "b. bahwa dua;", "www.peraturan.go.id"],
        ["PRESIDEN REPUBLIK INDONESIA", "- 3 -", "Pasal 1", "Teks.", "2020, No.67", "4"],
    ]
    lines = clean_lines(pages)
    assert lines == ["PRESIDEN", "REPUBLIK INDONESIA", "UNDANG-UNDANG", "Menimbang: a.",
                     "bahwa satu;", "b. bahwa dua;", "Pasal 1", "Teks."]


def test_old_spelling_closing_and_penjelasan():
    """UU 1/1945: 'Djakarta, tanggal ...' closes the body and 'PENDJELASAN' starts the
    explanation (they used to be appended to the last pasal)."""
    lines = ["Pasal 1", "Teks satu.", "Pasal 2", "Undang-Undang ini mulai berlaku pada hari diumumkan.",
             "Djakarta, tanggal 23 Nopember 1945,", "PRESIDEN REPUBLIK INDONESIA,", "SOEKARNO.",
             "Diumumkan pada tanggal 23 Nopember 1945.", "PENDJELASAN UNDANG-UNDANG 1945 NO. 1",
             "Di dalam menjalankan Undang-Undang ini Pemerintah telah memenuhi kesulitan."]
    doc = parse_lines(lines)
    pasal2 = [b for b in doc.blocks if b.kind == "text"][1]
    assert pasal2.text == "Undang-Undang ini mulai berlaku pada hari diumumkan."
    assert any(b.kind == "closing" and b.text.startswith("Djakarta") for b in doc.blocks)
    assert any(b.kind == "penjelasan" for b in doc.blocks)
    to_akn(to_bluebell(doc), "/akn/id/act/uu/1945/1", "act")


def test_list_between_chapter_and_first_pasal_is_text():
    # UU 19/2003 and UU 11/2020 failed with "markup in text: 'POINT 1.'": a numbered list
    # after a BAB heading, before its first Pasal, was written as POINT inside the chapter.
    from hukum_rapih.pdf.structure import Block, Document

    doc = Document([
        Block("bab", "BAB I", "KETENTUAN UMUM"), Block("pasal", "Pasal 1"),
        Block("ayat", "(1)", "Satu."), Block("bab", "BAB XI", "LAIN-LAIN"),
        Block("text", "", "Dalam bab ini:"), Block("item", "1.", "pertama;", 1),
        Block("item", "2.", "kedua.", 1), Block("pasal", "Pasal 2"), Block("text", "", "Dua."),
    ])
    text = to_bluebell(doc)
    assert "POINT 1." not in text and "1. pertama;" in text
    xml = to_akn(text, "/akn/id/act/uu/2003/19", "act")
    xml = xml.decode() if isinstance(xml, bytes) else xml
    assert "pertama" in xml and xml.count("<article") == 2


def test_keyword_like_word_in_text_is_not_leaked_markup():
    import pytest

    from hukum_rapih.akn.build import LeakedMarkupError, to_akn

    to_akn("BODY\n  ART 1 -\n    TR: Tegangan Rendah\n", "/akn/id/act/uu/2024/59", "act")
    with pytest.raises(LeakedMarkupError):
        to_akn("BODY\n  ART 1 -\n    \\ART 2 - leaked\n", "/akn/id/act/uu/2024/59", "act")


def test_treaty_heading_printed_in_a_lampiran_is_text():
    """A Lampiran keeps its printed lines (rule S23): a treaty's "ARTICLE 9" or "PART I" there
    is text, while the same line in the Penjelasan still counts as leaked (2026-11-28: UU
    15/2009 kept its old text over it)."""
    import pytest

    from hukum_rapih.akn.build import LeakedMarkupError, to_akn

    def law(penjelasan: str, lampiran: str) -> str:
        return ("BODY\n  ART 1 -\n    Teks.\n\n"
                f"ATTACHMENT Penjelasan\n  PART - PENJELASAN\n    {penjelasan}\n\n"
                f"ATTACHMENT Lampiran\n  PART - LAMPIRAN\n    {lampiran}\n")

    to_akn(law("Cukup jelas.", "\\ARTICLE 9 PARAGRAPH 2 of the Convention"),
           "/akn/id/act/uu/2009/15", "act")
    to_akn(law("Cukup jelas.", "\\PART I. GENERAL"), "/akn/id/act/uu/2009/15", "act")
    with pytest.raises(LeakedMarkupError):
        to_akn(law("\\ART 2 - leaked", "Teks."), "/akn/id/act/uu/2009/15", "act")


def test_para_before_a_word_in_capitals_is_text():
    """"PARA" marks a plural in Indonesian; markup's PARA comes before its number (2026-11-28:
    UU 2/2023 kept its old text over "PARA PEJABAT BERWENANG")."""
    import pytest

    from hukum_rapih.akn.build import LeakedMarkupError, to_akn

    doc = parse_lines(["Pasal 1", "PARA PEJABAT BERWENANG", "Pasal 2", "Teks."])
    to_akn(to_bluebell(doc), "/akn/id/act/uu/2023/2", "act")
    for leaked in ("\\PARA (1) Teks.", "\\PARA Ayat (1)"):
        with pytest.raises(LeakedMarkupError):
            to_akn(f"BODY\n  ART 1 -\n    {leaked}\n", "/akn/id/act/uu/2023/2", "act")
