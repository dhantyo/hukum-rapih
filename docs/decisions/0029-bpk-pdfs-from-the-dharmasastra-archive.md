# 0029 BPK's PDFs come first from the archive.org copies of the dharmasastra archive

Date: 2026-11-28 · Decided by: the operator; change by Claude

## What

- `download` in `pipeline/src/hukum_rapih/sources/peraturan_bpk.py` gets a BPK file from three
  places, in order: the archive.org copy that github.com/frenicohansen/idn-dharmasastra-archive
  (CC0) maps to BPK's URL of the file, BPK itself, and the Hugging Face mirror.
- The copy is used only when its sha256 is the mapping's, and also the file's recorded `sha256`
  when the record has one. Otherwise the importer goes on to BPK. URLs are compared after
  percent-decoding.
- The file's `fetched_from` and its manifest line's `note` name the copy, as for the Hugging
  Face mirror. The manifest line keeps BPK's URL as `source_url`: the bytes are BPK's.
- The mappings are read from GitHub once per importer process (a tarball of the repository,
  `sources/dharmasastra.py`) and are not copied into this repository. When GitHub cannot be
  read, the importer goes to BPK as before.

## Why

Every BPK download passes Cloudflare (`sources/bpk_session.py`), the slowest and most fragile
step of an import. On 2026-11-28 the archive held 1,830 of our 2,054 UU files and 64 of our 170
Perppu files, matched by sha256. archive.org needs no clearance, and the hash check makes its
copy the same file as BPK's.

## What we gave up

- Most downloads now depend on GitHub and archive.org. When either fails, BPK serves the file,
  so the cost is time, not a wrong text.
- The detail pages still come from BPK; only the PDFs skip it.
- The copies are not written to the record's `archive_url`: that field holds our own copies
  (decision 0014), and `reparse-bpk` does not read the archive's.
