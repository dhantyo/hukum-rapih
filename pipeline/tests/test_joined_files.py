"""The files of a law joined into one text (decision 0023): a file that brings no Penjelasan or
Lampiran heading starts a Lampiran once the law's own text has ended, and goes on with the body
or a Lampiran that is still open (rule S34 of docs/parser-rules.md)."""

import pytest

from hukum_rapih.akn.bluebell import to_bluebell
from hukum_rapih.akn.build import to_akn
from hukum_rapih.pdf.structure import parse_files

LAW = ["UNDANG-UNDANG REPUBLIK INDONESIA", "NOMOR 13 TAHUN 2014", "TENTANG", "PENGESAHAN PERJANJIAN EKSTRADISI",
       "Menimbang : a. bahwa x;", "Pasal 1", "Mengesahkan Perjanjian Ekstradisi.", "Pasal 2",
       "Undang-Undang ini mulai berlaku pada tanggal diundangkan.", "Disahkan di Jakarta",
       "pada tanggal 21 Juli 2014"]
PENJELASAN = ["PENJELASAN", "ATAS", "UNDANG-UNDANG REPUBLIK INDONESIA", "NOMOR 13 TAHUN 2014", "I. UMUM",
              "Teks.", "II. PASAL DEMI PASAL", "Pasal 1", "Cukup jelas.", "Pasal 2", "Cukup jelas.",
              "TAMBAHAN LEMBARAN NEGARA REPUBLIK INDONESIA NOMOR 5560"]
# a treaty file opens with its own name and headings, in English, with no LAMPIRAN heading
TREATY = ["EXTRADITION TREATY", "BETWEEN", "THE REPUBLIC OF INDONESIA", "AND", "THE REPUBLIC OF INDIA",
          "PREAMBLE", "ARTICLE 1", "Obligation to Extradite", "CHAPTER I", "PART I"]
# the TLN's own header at the top of a Penjelasan printed as a file of its own (UU 2/2016)
TLN_HEAD = ["TAMBAHAN", "LEMBARAN NEGARA R.I", "No. 5836 AGREEMENT. Pengesahan. Republik Indonesia.",
            "Republik Polandia. Bidang Pertahanan. Kerja Sama.", "Persetujuan. (Penjelasan Atas Lembaran Negara",
            "Republik Indonesia Tahun 2016 Nomor 10)"]


def blocks(doc, *kinds):
    return [(b.kind, b.label, b.text) for b in doc.blocks if b.kind in kinds]


@pytest.mark.parametrize("law", [LAW, LAW + PENJELASAN, LAW + PENJELASAN[:-1],
                                 LAW + PENJELASAN + ["Salinan sesuai dengan aslinya", "KEMENTERIAN SEKRETARIAT"]],
                         ids=["after the closing", "after the Penjelasan's closing", "in the Penjelasan",
                              "after a copy certification"])
def test_a_treaty_file_joined_after_the_laws_text_opens_a_lampiran(law):    # UU 13/2014, UU 4/2020
    doc = parse_files([law, TREATY])
    assert blocks(doc, "lampiran", "lampiran_text") == [
        ("lampiran", "LAMPIRAN", ""), *(("lampiran_text", "", line) for line in TREATY)]
    to_akn(to_bluebell(doc), "/akn/id/act/uu/2014/13", "act")       # its ARTICLE 1 is not leaked markup


def test_a_body_file_joined_before_the_closing_continues_the_body():     # UU 7/2017, in two files
    doc = parse_files([LAW[:7], LAW[7:] + PENJELASAN])
    assert blocks(doc, "pasal", "lampiran") == [("pasal", "Pasal 1", ""), ("pasal", "Pasal 2", "")]


@pytest.mark.parametrize("head", [[], TLN_HEAD], ids=["heading first", "after the TLN's header"])
def test_a_penjelasan_file_joined_opens_the_penjelasan(head):             # UU 19/2003, UU 2/2016
    doc = parse_files([LAW, head + PENJELASAN])
    assert blocks(doc, "penjelasan") == [
        ("penjelasan", "", "PENJELASAN ATAS UNDANG-UNDANG REPUBLIK INDONESIA NOMOR 13 TAHUN 2014")]
    assert not blocks(doc, "lampiran")


def test_a_file_joined_in_a_lampiran_continues_it():                      # UU 60/2024, in page ranges
    doc = parse_files([LAW + ["LAMPIRAN", "Tabel 1"], ["Tabel 2"]])
    assert blocks(doc, "lampiran", "lampiran_text") == [
        ("lampiran", "LAMPIRAN", ""), ("lampiran_text", "", "Tabel 1"), ("lampiran_text", "", "Tabel 2")]
