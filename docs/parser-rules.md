# Parser rules

Every rule the UU parser applies today (parser v17), where it lives and which test covers it.
Groundwork for the rewrite of `pipeline/src/hukum_rapih/pdf/structure.py`; the structure the
rules aim at is in [uu-grammar.md](uu-grammar.md).

Sources: the `PARSER_VERSION` comment and `git log -p` of `pdf/structure.py` and
`pdf/extract.py`, [parser-review-2026-11.md](parser-review-2026-11.md), the tests in
`pipeline/tests/`, and the code of `pdf/structure.py`, `pdf/extract.py`, `pdf/edges.py` and
`closing.py`. Laws are the ones that caused the rule. Tests are `file::function` in
`pipeline/tests/`; **new** marks a test added with this inventory. Ref = the rule exists because
of citations in the text (see [Citations](#citations)).

## Counts

| Layer | Rules | No test before | Tests added |
|---|---:|---:|---:|
| Page cleanup (`pdf/extract.py`, `pdf/edges.py`) | 26 | 2 | 2 |
| Line classification (`pdf/lines.py`) | 24 | 8 | 8 |
| Structure (`pdf/structure.py` `TABLE`) | 34 | 7 | 6 |
| Closing fields (`closing.py`) | 12 | 2 | 2 |
| **All** | **96** | **19** | **18** |

S17's test pins what it does today, which is a defect ([Known gaps](#known-gaps), G4). Three
more tests are `xfail(strict=True)`: they state what the rewrite must do and fail until it does.

## Page cleanup

PDF pages to cleaned printed lines, before anything is classified.

| ID | Rule | Cause | Code | Test |
|---|---|---|---|---|
| P1 | Printed lines rebuilt from word positions: words whose centres are within half a line height are one line | BPK stores justified text one word per line (v5) | `extract.rows`, `row_boxes` | `test_page_furniture::test_words_on_one_printed_line_are_joined` |
| P2 | Characters printed in white are left out | UU 29/2007 (v7) | `extract.visible` | `test_page_furniture::test_white_text_is_left_out` |
| P3 | A page covered by a picture (> 60%) is a scan and read with our OCR, not its text layer | UU 5/2026 (v6) | `extract.is_scan`, `page_lines` | `test_ocr::test_scans_are_read_with_ocr_when_available`, `test_typed_pages_are_not_ocrd` |
| P4 | OCR engine Indra, then Tesseract, then the PDF's own layer, said in the warnings | decision 0012 (v14) | `extract.page_lines` | `test_ocr::test_scans_fall_back_to_the_text_layer_without_tesseract` |
| P5 | Scanned pages: rows down to the page number and from the `SK No` serial down are header and footer | UU 100/2024 (v16) | `edges.edge_rows` | `test_edges::test_page_2_header_down_to_the_number_and_footer_are_cut_by_position`, `test_number_read_with_variations` |
| P6 | Position cut only in a known layout: number and serial on at least half of pages 2+ | Perda, Peraturan BPK lose nothing | `edges.detect_layout` | `test_edges::test_layout_is_detected_from_pages_2_plus_only`, `test_other_regulations_drop_nothing_by_position` |
| P7 | Page 1: letterhead lines above the title and a `SALINAN` stamp beside the crest | UU 100/2024, Perpres 46/2026 | `edges.edge_rows`, `_letterhead` | `test_edges::test_page_1_letterhead_and_footer_are_cut_but_the_enacting_formula_stays`, `test_salinan_stamp_beside_the_crest_is_cut_but_not_the_word_in_the_body` |
| P8 | A page-turn word is cut by position only right above the serial | UU 100/2024 | `edges.edge_rows` | `test_edges::test_page_turn_needs_the_serial_below_it`, `test_body_line_ending_in_dots_above_the_serial_stays` |
| P9 | After a position cut, the text rules for the running header are off (the enacting formula stays) | UU 100/2024 | `extract._clean_page(header_cut)` | `test_edges::test_uu_100_2024_header_and_footer_never_reach_the_text` |
| P10 | peraturan.go.id banner `Teks tidak dalam format asli…` removed | old UU from peraturan.go.id (2026-11-21) | `extract.NOISE_RE` | **new** `test_page_furniture::test_peraturan_go_id_banner_is_dropped` |
| P11 | OCR's stray bar at a line's start or end | UU 2/2021, 24/2022 | `extract._strip_edges` | `test_page_furniture::test_ocr_serials_and_bars` |
| P12 | Page number or serial printed level with a text line, cut from its end or start | UU 20/2023, 6/2021, 36/2014 | `extract.EDGE_NOISE_RE`, `LEAD_NOISE_RE` | `test_page_furniture::test_page_numbers_and_serials_on_a_text_line` |
| P13 | Short crest fragments above the running header, only there | UU 18/2025 (v7) | `extract._clean_page` | `test_page_furniture::test_crest_fragments_above_the_header_only` |
| P14 | DPR signature boxes in the header zone (`PDIP`, `FPG` …) | DPR "draft final" RUU | `extract.HEADER_TOKENS` | `test_structure::test_headers_and_page_numbers_removed` |
| P15 | Page numbers and lone `-` in the header zone (split `-` / `3` / `-`) | UU 2/1957, 19/1997 (v5) | `extract.PAGE_NO_RE`, `_clean_page` | `test_page_furniture::test_page_turn_words_and_split_page_numbers_are_dropped` |
| P16 | Running header `PRESIDEN` / `REPUBLIK INDONESIA` and OCR variants, pages 2+ | Pasal.id rules (v2) | `extract.RUNNING_HEADER_RE` | `test_structure::test_page_headers_and_numbers_removed_after_page_one` |
| P17 | `SALINAN` stamp in page 1's header zone | peraturan.go.id PDFs | `extract._clean_page` | `test_structure::test_page_headers_and_numbers_removed_after_page_one` |
| P18 | Never content, anywhere: `SK No` serials, site URLs, gazette header `2022, No.4`, browser print header and footer | Pasal.id; UU 19/2003 (v9) | `extract.NEVER_CONTENT_RE` | `test_page_furniture::test_browser_print_header_and_footer_are_not_content`, `test_ocr_serials_and_bars`; `test_structure::test_page_headers_and_numbers_removed_after_page_one` |
| P19 | Never content: `Halaman 2 dari 10`, `3 of 12`, djpp and ditjen marks, `file:///` paths | Pasal.id rules | `extract.NEVER_CONTENT_RE` | **new** `test_page_furniture::test_print_and_site_marks_are_dropped_anywhere_on_a_page` |
| P20 | Trailing page numbers and dashes in the footer | peraturan.go.id PDFs | `extract._clean_page` | `test_structure::test_page_headers_and_numbers_removed_after_page_one` |
| P21 | Page-turn words (`Pasal 2…`, `d. bahwa . . .`) in a page's last 2 lines | UU 25/1956 (v5) | `extract.is_page_turn`, `CATCHWORD_ZONE` | `test_page_furniture::test_page_turn_words_and_split_page_numbers_are_dropped` |
| P22 | A long dot run is a form's dot leader, not a page-turn | UU 12/1953 | `extract.is_page_turn` | `test_page_furniture::test_form_dot_leaders_are_not_page_turn_words` |
| P23 | A page-turn word anywhere when a line within 3 starts with its words | UU 19/2001, 12/1964, 1/2009 | `extract.clean_lines`, `_announces` | `test_page_furniture::test_page_turn_words_in_the_middle_of_a_pdf_page`, `test_page_turn_word_just_after_its_heading` |
| P24 | A page-turn printed at the end of a text line is cut | UU 1/2009 | `extract._cut_page_turn_tail` | `test_page_furniture::test_page_turn_on_the_same_line_as_text` |
| P25 | Misread words of scanned pages corrected when the spell check is confident, after cleanup | decision 0013 (v15) | `extract.clean_lines`, `ocr_fix.fix_lines` | `test_ocr_fix.py` |
| P26 | Further PDFs of the same law (a separate Penjelasan, a treaty, decision 0023) read after it, each cleaned on its own; where each starts goes on to the structure (S34) | UU 19/2003 (v9), UU 13/2014 (v20) | `structure.parse_pdf(extra)`, `structure.parse_files` | `test_penjelasan::test_separate_penjelasan_pdf_is_read_after_the_law`, `test_joined_files.py` |

## Line classification

What a single line is, read from its text alone: the registry in `pdf/lines.py` (rewrite step
1, done). Each entry carries its ids, the law that caused it and its test; Code names the entry:
`JOIN_PASAL` and `REPAIRS` (in `normalise`) repair heading lines, and one `RULES` entry per
`Kind` classifies a line, with the fields it captured. `classify` returns every class a line
matches; the structure layer picks the one that counts. Each class also has example lines, printed
in the law named where there is one, in `test_line_classes::test_a_line_is_of_its_class_with_its_fields`.

| ID | Rule | Ref | Cause | Code | Test |
|---|---|---|---|---|---|
| L1 | `Pasal` alone on a line joined with the number below | | scans, UU 18/2025 (v5) | `JOIN_PASAL` | `test_headings::test_pasal_number_on_its_own_line` |
| L2 | OCR letters for digits in a heading number: `Pasal S1`, `Pasal 1lA` | | UU 12/2022 (v12) | `REPAIRS` L2 | `test_headings::test_ocr_letters_for_digits_and_spaced_marks_in_headings` |
| L3 | OCR specks around a Pasal heading dropped, but `Pasal 5,` and `Pasal 5;` stay: a reference broken onto its own line | yes | UU 135/2024, 29/2024, 11/2022 (v10-12) | `REPAIRS` L3 | `test_headings::test_ocr_speck_before_a_pasal_heading` |
| L4 | A heading's full stop dropped: `Pasal 1.`, `BAB I.`, `BAGIAN II.` | | UU 25/1956, 6/1964 (v5) | `REPAIRS` L4 | `test_headings::test_headings_with_a_full_stop_and_old_numbering` |
| L5 | `PasalI`, `PASAL 3`, `Pasal12` read as `Pasal N` | | OCR, UU 18/2025 (v7) | `REPAIRS` L5 | **new** `test_headings::test_ocr_glued_or_capital_pasal_heading_is_read_as_pasal_n` |
| L6 | `BAB` + Roman number | | all | `Kind.BAB` | `test_headings::test_headings_with_a_full_stop_and_old_numbering` |
| L7 | `Bab Pertama`, `Bab Kedua` … (ordinal in words) | | 1950s (v5) | `Kind.BAB`; `structure.ORDINAL` | **new** `test_headings::test_bab_numbered_in_words` |
| L8 | `Bagian Kesatu`, `BAGIAN II` | | all; Roman in the 1950s (v5) | `Kind.BAGIAN` | **new** `test_headings::test_bagian_and_paragraf_have_one_title_line_and_need_a_bab` |
| L9 | `Paragraf 1` | | all | `Kind.PARAGRAF` | **new** `test_headings::test_bagian_and_paragraf_have_one_title_line_and_need_a_bab` |
| L10 | `Pasal` + Arabic number with an optional capital (`128A`) or a Roman number, the whole line | | all | `Kind.PASAL` | `test_structure::test_structure` |
| L11 | Ayat `(n)` at a line start | | all | `Kind.AYAT` | `test_structure::test_cross_reference_is_not_a_heading` |
| L12 | List markers `a.` and `1.` at a line start | | all | `Kind.LIST_ITEM` | `test_structure::test_hyphen_join_and_nesting` |
| L13 | Preamble labels `Menimbang`, `Mengingat`, `Menetapkan`, `MEMUTUSKAN`, `Dengan persetujuan (bersama)` | | all | `Kind.PREAMBLE` | `test_headings::test_preamble_lists_on_the_label_line_and_after_a_colon` |
| L14 | `DENGAN RAHMAT TUHAN YANG MAHA ESA` and `PRESIDEN REPUBLIK INDONESIA,` are preamble, not title | | all | `Kind.OPENING` | **new** `test_headings::test_enacting_formula_lines_are_preamble_not_title` |
| L15 | Crest caption (`PRESIDEN`, `REPUBLIK INDONESIA`, `SALINAN`) is not the title | | UU 6/1964 (v5) | `Kind.CREST_CAPTION` | `test_headings::test_crest_caption_is_not_the_title` |
| L16 | Penjelasan heading: `PENJELASAN [ATAS] [citation]`, `PENDJELASAN`, `MEMORI PENJELASAN`, a final dot, `No.` | | UU 1/1945, 3/1949, 4/1956, 6/1967 (v3, v7) | `Kind.PENJELASAN` | `test_penjelasan::test_penjelasan_heading_with_a_full_stop`, `test_penjelasan_with_lettered_sections`; `test_structure::test_old_spelling_closing_and_penjelasan` |
| L17 | `PENJELASAN UMUM` on one line opens Penjelasan and Umum | | UU 25/1956 (v5) | `Kind.PENJELASAN_UMUM` | `test_penjelasan::test_penjelasan_umum_on_one_line` |
| L18 | `I. UMUM`, `A. PENJELASAN UMUM.`, OCR `1. UMUM`; `II. PASAL DEMI PASAL`, `B. …` | | UU 6/1967, 2/2025 (v8) | `Kind.PENJELASAN_PART` | `test_penjelasan::test_penjelasan_with_lettered_sections`, `test_penjelasan_after_the_copy_certification_is_kept` |
| L19 | `I.` or `II.` alone on a line before its section name is dropped | | Penjelasan layout | `Kind.PENJELASAN_PART` | **new** `test_penjelasan::test_penjelasan_sections_with_the_numeral_on_its_own_line` |
| L20 | Penjelasan labels `Ayat (1)`, `Huruf a`, `Angka 2` | | all | `Kind.PENJELASAN_LABEL` | **new** `test_penjelasan::test_penjelasan_labels_for_ayat_huruf_and_angka` |
| L21 | Closing lines: `Agar setiap orang …`, `Disahkan di`, `Diundangkan di`, `Ditetapkan di`, `Djakarta, tanggal`, LN and TLN lines | | UU 4/2009, 25/1956, 1/1945 (v3, v5) | `Kind.CLOSING` | `test_closing::test_closing_kept_line_by_line`, `test_old_closing_formula`; `test_structure::test_old_spelling_closing_and_penjelasan` |
| L22 | Old and misread closing forms: `Dikeluarkan di`, `Disahkah di`, `Disjahkan di`, `Diumumkan` | | old spelling, OCR | `Kind.CLOSING` | **new** `test_closing::test_closing_variants_end_the_last_pasal` |
| L23 | `LAMPIRAN`, `LAMPIRAN I` … | | UU 14/2013 (v7) | `Kind.LAMPIRAN` | `test_penjelasan::test_lampiran_after_the_penjelasan` |
| L24 | `Salinan sesuai dengan aslinya` starts the copy certification | | UU 14/2013, 2/2025 (v7) | `Kind.SALINAN` | `test_penjelasan::test_lampiran_after_the_penjelasan`, `test_penjelasan_after_the_copy_certification_is_kept` |

## Structure

What a line means given what came before: the state machine in `pdf/structure.py` (rewrite
step 2, done). `State` is the part being read (front, preamble, body, an amending law's Pasal I,
closing, certification, the Penjelasan's Umum, Pasal demi Pasal and an amending law's Pasal I,
Lampiran). `Context` holds the counters, the open lists, the document so far and `part`, the
part that CLOSING and SALINAN lie over and give way to (`settle`). `TABLE` gives each state its
cells in the order they are tried: a cell is a line class, a guard (counters, and a read-only
`View` of the lines around for the look-ahead rules and of where each joined file starts), an
action and the next state.

Code names the cells (`Cell.name`) that carry out the rule, then the guards and helpers they
use; a cell may sit in several states. `test_structure_table::test_a_state_reads_its_lines`
reads each rule's lines from its state, and
`test_structure_table::test_every_rule_sits_in_the_cells_the_inventory_names` checks the Code
column against the cells' ids.

| ID | Rule | Ref | Cause | Code | Test |
|---|---|---|---|---|---|
| S1 | A Pasal heading is taken only as the next number; anything else is a reference that starts a wrapped line | yes | v1 | `pasal_first`, `pasal`, `pasal_of_amending_law`; `pasal_follows` | `test_structure::test_cross_reference_is_not_a_heading`, `test_structure` |
| S2 | `Pasal 2A` after `Pasal 2` | | Lampiran II item 234 | `pasal_first`, `pasal`; `pasal_follows` | **new** `test_headings::test_inserted_pasal_with_a_letter_follows_its_number` |
| S3 | A number off the sequence is a misprint when it follows a sentence end and the next heading (within 400 lines) confirms it; warned | yes | UU 19/1948, 29/1948, 1/1951 (v13) | `pasal`; `misprinted`, `next_heading`, `after_sentence`, `NEXT_HEADING_WITHIN` | `test_headings::test_misprinted_heading_numbers_confirmed_by_the_next_heading` |
| S4 | A heading after `… berikut:` is a quoted pasal, never a misprint or skip | yes | UU 7/2021 (v17) | `pasal`; `quote_follows` | `test_amending_laws::test_quoted_pasal_of_an_amended_law_is_not_taken_as_a_skipped_number` |
| S5 | BAB in sequence; the same number again only when a capitals title follows (kept as printed) | | UU 19/1997 | `bab_before_pasal`, `bab`; `title_follows` | `test_headings::test_bab_printed_twice_is_kept_as_printed` |
| S6 | BAB title: the capitals lines up to the next heading; old laws: up to 4 short lines in normal capitals before a heading | | UU 25/1956 (v5) | `bab_before_pasal`, `bab`; `take_title` | `test_headings::test_headings_with_a_full_stop_and_old_numbering` |
| S7 | Bagian and Paragraf only inside a BAB; their title is the next line | | Lampiran II item 70 | `bagian`, `paragraf`; `take_title` | **new** `test_headings::test_bagian_and_paragraf_have_one_title_line_and_need_a_bab` |
| S8 | Ayat only as the next number; a new ayat closes the lists | | v1 | `ayat` | `test_structure::test_cross_reference_is_not_a_heading` |
| S9 | Numbers inside a lettered item (and letters inside a numbered one) nest one deeper; lists reset per pasal | | b14f553f | `list_item`; `place` | `test_structure::test_numbers_inside_letters_and_back`, `test_list_nesting_resets_per_pasal` |
| S10 | A list starts only at `a.` or `1.`; a lone `c.` is a reference wrapped onto the line | yes | v1 | `list_item`; `place` | **new** `test_structure::test_a_list_starts_only_at_a_or_1` |
| S11 | Lines joined with a space; `Undang-` + `Undang` without | | v1 | `title_continues`, `preamble_text`, `text`; `append`, `join` | `test_structure::test_hyphen_join_and_nesting` |
| S12 | Spacing tidied: `Undang- Undang`, space before `,;:.)`, after `(`, inside quotes | | justified layout | `tidy` (in `parse_files`, after the table) | **new** `test_structure::test_spacing_of_joined_lines_is_tidied` |
| S13 | Before the first label every line is title, joined | | v1 | `opening`, `crest_caption`, `title`, `title_continues` | `test_headings::test_crest_caption_is_not_the_title` |
| S14 | Preamble lists: the first item on the label's line or after a lone `:`; flat | | UU 14/2013, 6/1964 (v5) | `preamble_label`, `label_alone`, `preamble_item` | `test_headings::test_preamble_lists_on_the_label_line_and_after_a_colon` |
| S15 | `Dengan persetujuan …` is its own preamble part, not glued to the last Mengingat item | | v5 | `preamble_label` | `test_headings::test_preamble_lists_on_the_label_line_and_after_a_colon` |
| S16 | After the last pasal a closing line opens the closing; every later line is a closing line as printed; the `Agar …` sentence joins until its full stop | | UU 4/2009, 25/1956 (v5) | `closing_opens`, `closing_sentence`, `closing_line`, `closing_in_salinan`; `settle` | `test_closing::test_closing_kept_line_by_line`, `test_old_closing_formula` |
| S17 | A `RANCANGAN` line after the closing is not a closing line | | RUU drafts | `closing_gives_way` | **new** `test_structure_table::test_the_closing_lies_over_its_part_and_gives_way_to_it` (pins G4) |
| S18 | The Penjelasan starts only after a pasal, once | | v1 | `penjelasan_opens`; `penjelasan_to_come` | partly: `test_penjelasan::test_penjelasan_quoted_in_a_lampiran_after_the_penjelasan_stays_in_the_lampiran` |
| S19 | In the Penjelasan a pasal heading in sequence, or any later pasal of the law after a sentence end | | UU 2/1962 (v13) | `p_pasal`; `p_pasal_follows` | `test_penjelasan::test_penjelasan_may_skip_pasal` |
| S20 | A misprinted pasal in the Penjelasan, confirmed by the next heading | | v13 | `p_pasal`; `misprinted` | **new** `test_penjelasan::test_misprinted_pasal_in_the_penjelasan_is_kept_when_the_next_one_confirms_it` |
| S21 | An amending law's Penjelasan has `Pasal I`, `Pasal II`; Arabic pasal inside are labels | | UU 2/2025, 11-13/2022 (v8, v12) | `p_pasal_i`; `Context.amending_law` | `test_penjelasan::test_penjelasan_after_the_copy_certification_is_kept`; `test_amending_laws::test_amending_penjelasan_puts_angka_above_ayat` |
| S22 | Penjelasan Umum: a new paragraph after each sentence end | | v1 | `paragraph`, `text_after_part` | **new** `test_penjelasan::test_penjelasan_sections_with_the_numeral_on_its_own_line` |
| S23 | A Lampiran keeps its lines as printed, a Penjelasan heading too, unless it names the law itself (number and year of the title) and the law's Penjelasan has not come: then it opens the Penjelasan, read from a separate PDF after the Lampiran. A Perppu enacted by the law is printed whole in the Lampiran, its Penjelasan too | | UU 14/2013, 13/2022 (v7, v12), UU 9/2017 (v18) | `lampiran_opens`, `penjelasan_in_lampiran`, `lampiran_in_lampiran`, `lampiran_text`; `penjelasan_of_the_law`, `CITED_RE`, `PENJELASAN_TITLE_LINES` | `test_penjelasan::test_lampiran_after_the_penjelasan`, `test_penjelasan_quoted_in_a_lampiran_after_the_penjelasan_stays_in_the_lampiran`, `test_penjelasan_of_an_enacted_perppu_stays_in_the_lampiran_and_the_laws_own_follows`; `test_structure_table::test_a_state_reads_its_lines` |
| S24 | The copy certification (`Salinan sesuai dengan aslinya` …) after the first pasal is left out with a warning; inside a Lampiran without one | | UU 14/2013 | `salinan_opens`, `salinan_in_lampiran`, `salinan_line` | `test_penjelasan::test_lampiran_after_the_penjelasan` |
| S25 | The certification skip ends at a Penjelasan or Lampiran heading, or after 15 lines with a warning | | UU 2/2025 (v8) | `salinan_runs_out`, `salinan_ends`; `SALINAN_MAX` | `test_penjelasan::test_penjelasan_after_the_copy_certification_is_kept`, `test_a_runaway_copy_certification_skip_is_capped` |
| S26 | A first `Pasal I` before any BAB makes the law amending | | UU 18/2025, 14/2013 (v7) | `pasal_1_read_as_i`, `pasal_i`, `pasal_of_amending_law` | `test_amending_laws::test_amending_law_keeps_quoted_pasal_inside_pasal_i` |
| S27 | In an amending law, BAB, Bagian, Paragraf and Arabic Pasal lines are the amended law's quoted wording: text of Pasal I | yes | UU 18/2025, 14/2013 (v7) | `quoted_pasal_1`, `quoted_heading` | `test_amending_laws::test_amending_law_keeps_quoted_pasal_inside_pasal_i` |
| S28 | `Pasal I.` followed by `Pasal 2` with no amendment wording was a misprint of Pasal 1 | | UU 16/1953 | `own_pasal_2`; `amends_so_far` | `test_headings::test_misprinted_pasal_i_in_an_ordinary_law` |
| S29 | The law's own `Pasal 2` after amendments in Pasal I: after a finished sentence, no quoted Pasal 1 | | UU 2/1953, 12/1957 | `own_pasal_2`, `quoted_pasal_1` | `test_amending_laws::test_own_pasal_2_after_amendments_in_pasal_i` |
| S30 | OCR's `Pasal 1` read as `Pasal I` when the title says PERUBAHAN and `Beberapa ketentuan … diubah` follows; warned | | UU 18/2025 (v7) | `pasal_1_read_as_i`, `pasal_1_read_as_i_in_bab`; `reads_as_amending` | `test_amending_laws::test_ocr_reads_pasal_i_as_pasal_1` |
| S31 | A document is amending when its first pasal has a Roman number | | v7 | `Document.amending` (outside the table) | `test_amending_laws::test_amending_law_is_recognised_from_its_first_pasal` |
| S32 | Before the Penjelasan's first pasal a part line (`I. UMUM`, `II. PASAL DEMI PASAL`) opens its part; the numeral alone on its line is dropped | | UU 6/1967, 2/2025 (v8) | `part_numeral`, `part` | `test_penjelasan::test_penjelasan_sections_with_the_numeral_on_its_own_line`, `test_penjelasan_with_lettered_sections` |
| S33 | `Ayat (1)`, `Huruf a`, `Angka 2` are labels only under a Penjelasan pasal | | Lampiran II item 190 | `p_label` | `test_penjelasan::test_penjelasan_labels_for_ayat_huruf_and_angka` |
| S34 | A joined file (decision 0023) with no Penjelasan or Lampiran heading in its first lines starts a Lampiran once the law's own text has ended (its closing read, or its Penjelasan open); in the body or a Lampiran it goes on with what is open (a body or a Lampiran in parts). A copy certification ends with its file | | 2026-11-28: UU 13/2014 and 17 other ratification laws had the treaty, a file of its own, as Penjelasan or closing text (v20) | `file_opens_lampiran`, `salinan_ends_at_file`; `file_opens_no_part`, `file_starts`, `FILE_HEAD_LINES` | `test_joined_files.py` |

## How to add or change a rule

Run these from `pipeline/`.

1. Find the rule. Look up its id in the inventory above. For a new rule, add a row with the next
   free id and the law that caused it (date and example: "2026-11-27: UU 9/2017 ...").
2. Reproduce it with `uv run hukum-rapih explain <law-id | PDF | stored text> --from N --to M`.
   It prints, for each line, the state before, the cell that read it (with its rule ids), the
   kinds the line registry gave it and the state after. `--state` and `--cell` narrow it down.
   It reads a cached PDF without OCR or a stored text, and says when a scanned page was skipped.
3. Make the change in the layer that owns it.
   - A line class (what one line is on its own): add or change a `Rule` in `pdf/lines.py`, with
     its inventory ids, cause and a test in `tests/test_line_classes.py` or the topic's file.
   - Structure (what a line means after what came before): add or change a `Cell` (guard,
     action, next state) in the row of `TABLE` it belongs to, in `pdf/structure.py`. Never an
     `if` in the driver or in an action (the ratchet test fails it). Add a table test with lines
     printed in the law to `tests/test_structure_table.py`.
4. List the id in the Code or Cell column of the inventory; the cell's `ids` carry the same id
   (`test_every_rule_sits_in_the_cells_the_inventory_names` checks it).
5. Run `uv run python scripts/parser_identity.py`. Classify every document that differs as an
   intended fix or a regression. A change meant to keep the output must show zero differences.
6. If the output changes, bump `PARSER_VERSION` and add a line to its comment with a dated
   example. Decide whether `PARSER_REDO_BELOW` (or `OCR_REDO_BELOW`) moves, by the rule in
   `pipeline/AGENTS.md`.
7. Check a stored text against a fresh parse with `uv run python scripts/compare_reparse.py <id>`,
   and keep `scripts/regress.py` and `uv run pytest` green.

`explain` uses the real driver: `parse_lines(lines, observe)` calls `observe` with a `Trace` for
every cell reading (`step` in `pdf/structure.py`). The observer cannot change the output, and
`tests/test_explain.py` checks it.

## Closing fields

`closing.py` reads the stored closing lines (Bluebell `CONCLUSIONS`) into fields.

| ID | Rule | Cause | Code | Test |
|---|---|---|---|---|
| C1 | `Agar (supaya) setiap orang …` is the order to promulgate | UU 4/2009 | `ORDER_RE` | `test_closing::test_modern_closing` |
| C2 | `Disahkan`, `Disahkah`, `Disjahkan`, `Ditetapkan`, `Dikeluarkan` [di place] [pada]: the signing | UU 11/2008, 14/2008 | `SIGNED_RE` | `test_closing::test_modern_closing`, `test_line_breaks_and_blank_place` |
| C3 | `Diundangkan`, `Diumumkan` [di place] [pada tanggal date]: the promulgation | UU 30/1947, 25/1956 | `PROMULGATED_RE` | `test_closing::test_1947_closing`, `test_1956_closing_with_cosigner` |
| C4 | `Djakarta, tanggal …` alone is the signing's place and date | UU 1/1945 | `OLD_PLACE_DATE_RE` | **new** `test_closing::test_old_place_and_date_line_is_the_signing` |
| C5 | `(pada) tanggal …` is the date of the open block | all | `DATE_RE` | `test_closing::test_modern_closing` |
| C6 | LN line with the year before or after the number | UU 4/2009, 25/1956 | `LN_RE` | `test_closing::test_modern_closing`, `test_1956_closing_with_cosigner` |
| C7 | `ttd.` ends an office printed without a comma | UU 19/1997 | `TTD_RE` | `test_closing::test_offices_without_comma_and_a_misprinted_disahkan` |
| C8 | An office over two lines (`… MANUSIA` / `REPUBLIK INDONESIA,`) | UU 4/2009 | `CONTINUES_RE` | `test_closing::test_modern_closing` |
| C9 | An office ends in a comma or starts with an office word; the next line is the name; later pairs are co-signers | UU 25/1956, 30/1947 | `_is_office`, `person` | `test_closing::test_1956_closing_with_cosigner`, `test_1947_closing` |
| C10 | A second `Disahkan` block is the promulgation, misprinted, with a note | UU 31/1999 | `parse` | `test_closing::test_offices_without_comma_and_a_misprinted_disahkan` |
| C11 | Fields not printed are left out | all | `parse` | `test_closing::test_nothing_invented_from_nothing`, `test_1947_closing` |
| C12 | The closing lines are read back from a stored text's `CONCLUSIONS` | v7 | `conclusions` | **new** `test_closing::test_closing_lines_are_read_back_from_a_stored_text` |

## Citations

Six parser rules exist only to keep citations from being read as structure (Ref = yes above):
L3, S1, S3, S4, S10, S27. The parser never reads a citation; it only avoids them.

Citations are read today outside the parser, in `relations.py` and `amendments.py`, on titles
and on an amending law's Pasal I. A link layer must reuse these, not add a second set:

| ID | Rule | Code | Test |
|---|---|---|---|
| R1 | A law cited in capitals: `UNDANG-UNDANG [DARURAT] [REPUBLIK INDONESIA] NOMOR/NO. n [DRT] TAHUN y`, `PERATURAN PEMERINTAH PENGGANTI UNDANG-UNDANG …`; to an id (`uu_4_2009`, `uu-drt_…`, `perppu_…`) | `relations.CITE`, `cite_id` | `test_relations::test_amendment_titles`, `test_enact_and_revoke` |
| R2 | Amends: `PERUBAHAN [KEDUA …] ATAS`, `MENGUBAH`, `MERUBAH` + R1 | `relations.AMEND_RE` | `test_relations::test_amendment_titles`, `test_not_an_amendment` |
| R3 | Revokes: `PENCABUTAN`, `MENCABUT` + R1 | `relations.REVOKE_RE` | `test_relations::test_enact_and_revoke` |
| R4 | Enacts: `PENETAPAN` + R1 + `MENJADI UNDANG-UNDANG` | `relations.ENACT_RE` | `test_relations::test_enact_and_revoke` |
| R5 | Changed, inserted, deleted pasal from `Ketentuan … diubah`, `Di antara … disisipkan … yakni …`, `Pasal n dihapus` | `relations.CHANGED_RE`, `BETWEEN_RE`, `INSERTED_RE`, `DELETED_RE`, `PASAL_RE` | `test_relations::test_changes_in_text` |
| R6 | OCR digits in cited pasal numbers (`4O`, `l3`, `Pasil`), `168` after `16A` read as `16B`; the text is never changed | `relations._num`, `_sequence` | `test_relations::test_ocr_misreads_in_numbers_only` |
| R7 | Pasal I split into numbered instructions and the new wording of each pasal | `amendments.py` (`HEAD`, `VERB`, `FOLLOWS`, `PASAL_RE`) | `test_amendments.py` |

R1 matches capitals only (titles). Body text cites in title case (`Undang-Undang Nomor 4 Tahun
2009 tentang …`, [uu-grammar.md](uu-grammar.md#citation-forms)).

## Known gaps

Found while building this inventory, measured on BPK's PDFs with parser v17. The xfail tests
pass once the rewrite handles them.

| ID | Gap | Evidence | Cell | Test |
|---|---|---|---|---|
| G1 | A closing line inside a Lampiran is taken out of it: in LAMPIRAN the closing cell comes before the Lampiran text | UU 12/2011: 52 lines of Lampiran II's examples become closing lines; UU 17/2016: the attached Perppu's 5 closing and TLN lines | `closing_in_lampiran` | xfail `test_penjelasan::test_closing_formula_quoted_in_a_lampiran_stays_in_the_lampiran` |
| G2 | `LAMPIRAN I` quoted in a Lampiran starts a new one | UU 12/2011: 4 Lampiran (I, II, II, I) instead of 2 | `lampiran_in_lampiran` | xfail `test_penjelasan::test_lampiran_heading_quoted_as_an_example_does_not_start_a_lampiran` |
| G3 | List levels `a)` and `1)` are text of the level-2 item | Lampiran II items 94-95 | `list_item`'s `place`, after a line class for `a)` and `1)` | xfail `test_structure::test_third_and_fourth_list_levels_are_items` |
| G4 | `RANCANGAN` after the closing is glued to the last closing line (`Disahkan di Jakarta RANCANGAN`), and `ATAS` to the Penjelasan heading | S17 | `closing_gives_way` | none |
| G5 | A date read from `Djakarta, tanggal 23 Nopember 1945,` keeps the comma | C4 | outside: closing fields (C4) | none |
| G6 | `NOISE_RE` eats the word after `backspace`: a banner followed by `Pasal 1` leaves `1`, then dropped as a page number | P10 | outside: page cleanup (P10) | none |
| G7 | An amending law with Arabic pasal takes the amended law's first quoted heading that is in sequence for its own (UU 7/2021: Pasal 4 in BAB III) | [parser-review](parser-review-2026-11.md), v17 | `pasal` | none |
| G8 | Old Penjelasan bodies (`A. Pemandangan Umum`, `Fatsal pertama.`) are one paragraph | UU 1/1945 | `paragraph` | none |
| G10 | A separate Penjelasan PDF whose heading is read inside a line is not opened: its text stays in the Lampiran before it | UU 9/2017: the stored text (v11) has `Tahun 2017 Nomor 190) PENJELASAN ATAS UNDANG-UNDANG … NOMOR 9 TAHUN 2017 …` as one Lampiran line; not re-read since, the file is not in the mirror | outside: page cleanup of the separate PDF | none |

## Design for the rewrite

### Candidates and evidence

**Grammar over classified lines.** Prototype (removed once the state machine replaced it; its code is `pipeline/scripts/grammar_prototype.py blocks` at commit 9abadd1c)
(lark LALR; each line classified by today's regexes, no sequence check; a context-free grammar
for front, body, closing, Penjelasan, Lampiran). On the 20 laws of `tests/regression.yaml`
(measured 2026-11-24, scans through their own text layer):

| Result | Laws |
|---|---|
| Same pasal count as the parser and the expected count | 13: UU 6/1964, 12/1964, 4/1971, 10/1980, 1/1981, 19/1997, 29/2007, 19/2001, 4/2009, 30/1947, 16/1947, 12/1971, 31/1999 |
| Parsed, wrong count | 3: UU 14/2013 (11 for 2), 2/2025 (31 for 2): quoted pasal of the amended law; UU 3/2019 (3 for 2): a reference on its own line |
| No parse | 4: UU 25/1956 (old chapter title), 2/1957 (`Bab Pertama` in quoted text), 18/2025 and 5/2026 (amending, OCR) |

The grammar does the easy part, which the parser already gets right. The rules that make the
other 7 pass (S1, S3, S4, S26-S30, S23) count, look ahead up to 400 lines or look at the title.
A context-free grammar cannot express them, so they would move into the classifier, which is
today's state machine under another name. Laws.Africa went the same way: Slaw (Treetop grammars
per country) is archived since 2022, and Indigo now imports with docpipe stages, one class per
rule (`indigo/pipelines/hier.py`: 29 stage classes, 19 of them `Identify…`), writing Bluebell for bluebell to parse.

**Table-driven state machine.** States: front, body, amending Pasal I, closing, certification,
Penjelasan, Lampiran. A table maps (state, line class) to an action and the next state, with
guards for the counters. Today the same machine is hidden in the order of 27 `if`s in
`Parser.step` and 7 mode flags; G1 and G2 are order bugs of exactly that kind (in a Lampiran a
closing line is checked first). A table makes "in Lampiran, a closing line is Lampiran text" one
visible cell, and each cell gets a test.

**Rule registry over the current code.** Name each rule above as a function and keep the order.
Cheapest, but the order stays implicit, so G1 and G2 stay possible.

### Recommendation

Keep three layers and give each the shape its rules have:

1. Page cleanup (P1-P26) stays a pipeline of steps, as now.
2. Line classification (L1-L24) becomes a registry: one named predicate per class, each with
   the law that caused it and its test from this inventory. Classes are context-free, so this
   layer has no state. **Done** (`pdf/lines.py`): the structure layer reads `Line` objects (text
   and the classes it matched, with their fields).
3. Structure (S1-S33) becomes a table-driven state machine over the classified lines. Counters
   (last pasal, BAB, ayat, open lists) are guards on transitions, not flags. **Done**
   (`pdf/structure.py`, [Structure](#structure)): same output as v17 on every local input.

Still to do: fix G1-G4, G7, G8 and G10, each in the cell the Known gaps table names (a fix changes
output, so it bumps `PARSER_VERSION`), then the [inline references](#inline-references) layer.

The regression set (20/20) and the tests listed here are the bar for each step of the rewrite.

### Changing the parser during the rewrite

A change to the parser starts with the next step of the rewrite. The three layers replaced the
`if` chain of the old `Parser.step` and its mode flags.

- `pipeline/tests/test_parser_rewrite_ratchet.py` keeps the structure layer a table: the old
  `Parser` stays gone, only the driver `step` reads the state, and the `if` statements of
  `pdf/structure.py` may only shrink. A new rule is a cell, or a guard of one, in the row of the
  state it belongs to; a new line class goes into the line registry.
- Lower `BASELINE_IFS` in the same commit as the shrink.
- Give every new or changed rule its inventory id, the law that caused it and its test in this
  file.
- The bar for each step is the regression set plus the inventory's tests, including the
  `xfail(strict=True)` ones the rewrite is meant to make pass.
- A step that keeps the output shows it with `pipeline/scripts/parser_identity.py`: the parser of
  `origin/main` and the working tree's on every local input (cached PDFs, stored texts) and on
  `--fuzz N` made-up documents (orders the laws hardly have), zero documents may differ.

### Inline references

A later layer links citations to `/akn/id/act/uu/2009/4` and to pasal eIds, written as Bluebell
`{{>href text}}` (`bluebell/akn.peg`, rule `ref`), which becomes Akoma Ntoso `<ref>`.

In every candidate this is a separate pass over the text of each finished block, after
structure, because resolving needs what structure knows: the pasal around a bare `ayat (1)`
(Lampiran II item 275), the pasal a Penjelasan block explains, and, inside an amending law's
Pasal I, that `Pasal 6` belongs to the amended law named at the start of Pasal I. With the state
machine the pass reads each block's path (BAB, pasal, ayat; Penjelasan or body; quoted or own).
With a grammar or a registry it reads the same from the tree or the block list. The layer does
not change the block structure, so it can be built after the rewrite and tested alone.

A grammar fits this layer, unlike the block structure: reference phrases are nested and
recursive (`ayat (1), Pasal 7 ayat (2) dan ayat (4), Pasal 12, dan Pasal 13 ayat (3)`, where
`ayat (4)` belongs to Pasal 7), they have ranges and exceptions, and they need no counting.
Prototype: `pipeline/scripts/refs_prototype.py` (lark LALR, run at each anchor such as `Pasal 4` or
`Undang-Undang`, keeping the longest prefix the grammar accepts through lark's interactive
parser). It reads all 7 example forms of Lampiran II items 44, 47, 272-276 and 283 as whole
phrases, and finds 1,054 phrases at 1,407 anchors in the stored texts of UU 4/2009 and UU
12/2011 in a fraction of a second (measured 2026-11-24; precision not yet checked by hand).
Indigo does the same for provision references (`indigo/analysis/refs/provision_refs.peg`, a
Canopy PEG run after regex matchers for whole works).

How it fits our code:

- The law part of the grammar takes R1's alternatives (`relations.CITE`) case-insensitively,
  and `relations.cite_id` turns a match into the target id; `relations.from_title` can then call
  the same grammar, so there is one citation grammar.
- `Undang-Undang ini` is the law itself; a kind without a number (`Peraturan Pemerintah`) gets
  no link.
- `akn/bluebell.py` writes the reference after escaping the text around it (`escape` escapes
  `{{` today).
