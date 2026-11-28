# Upstream sources

What we know about each site we read, and from where it answers. Dated, newest facts win. The code that reads each site is in `pipeline/src/hukum_rapih/sources/`.

## peraturan.bpk.go.id (main source since 2026-11-21)

- Sits behind a Cloudflare managed challenge ("Verify you are human", 403). It is not geo-blocked.
- Scrapling `StealthyFetcher` with a real Chrome under xvfb passes it from GitHub runners (2026-11-21). The `cf_clearance` cookie and the browser's user agent then work in `curl_cffi` for detail pages and PDFs. `sources/bpk_session.py` reuses one clearance per workflow run. Plain Playwright, SeleniumBase UC and Camoufox failed on the same runners.
- Browser tests against Cloudflare are meaningless from the Claude cloud container: its proxy re-terminates TLS, so every browser has a non-Chrome fingerprint.
- Listing pages, page size and the `jenis` codes per regulation type are in `sources/peraturan_bpk.py`. Detail pages give tanggal pengundangan and berlaku, LN/TLN, subjek, Uji Materi, and status with notes.
- BPK's retyped copies of old laws seem to use modern spelling (UU 6/1964 "yang" for "jang", UU 30/1947 "Yogyakarta" for "Jogjakarta"). BPK's UU 19/1997 names SOEHARTO under the State Secretary too, likely a retyping error. Kept as printed, pending a lawyer's review.
- The UUD 1945 is one entry, "UUD 1945 dan Amandemen" (`/Details/101646`), with six PDFs: `UUD45.pdf`, `UUD45_perubahan1.pdf` to `UUD45_perubahan4.pdf` and `UUD45_SatuNaskah.pdf`; it gives no dates (2026-11-28). The UUDS 1950 is UU 7/1950. Keppres 150/1959 (Dekrit Presiden) is `/Details/96516`.
- 2026-11-28, read by `import-bpk uud` and `import-bpk keppres`: `UUD45.pdf` prints no date. Each amendment ends "Ditetapkan di Jakarta / Pada tanggal 19 Oktober 1999" (capital P) and has no "Menetapkan": the MPR's lead-in "mengubah Pasal 5 Ayat (1), Pasal 7, … sehingga selengkapnya menjadi berbunyi sebagai berikut:" is followed by the pasal. A detail page opens without its slug (`/Details/96516`). Unlike the UUD entry, Keppres 150/1959's page gives tanggal and tempat penetapan (5 Juli 1959, Jakarta) and LN 1959/75; its one PDF prints the decree, then the UUD 1945 with its Penjelasan as reprinted in LN 1959/75 under "CATATAN", and BPK's retyping uses modern spelling ("berlakunya", "Juli").
- Status lists ("Mengubah", "Mencabut" …) are whole-law only and typed by hand. They also list the earlier amenders of a chain as amended or revoked (UU 23/2014 "Mencabut" UU 32/2004, UU 8/2005 and UU 12/2008, while its text names UU 32/2004 "sebagaimana telah diubah … terakhir dengan" UU 12/2008), and some pairs no text states (UU 18/1997 to UU 21/1948). A hint only (decision 0025).
- File names of a law's PDFs follow no pattern ("Hal. 1-150", "(i-409)", "_pjl", "Naskah Resmi", "Lamp. Eng"), and the listing order is not always the reading order (UU 23/1968 lists its lampiran first). See decision 0023.
- BPK has an Android app (`id.go.bpk.jdih.pro`) that may use an API. The APK was never obtained (APKPure blocked from runners, Google Play needs a login).
- A formal KIP request to BPK's PPID is the other route to the files.

## archive.org copies of BPK's PDFs: `frenicohansen/idn-dharmasastra-archive`

- A GitHub repository (CC0) whose workflow downloads BPK's PDFs, uploads each to archive.org
  (one item per type and year, `peraturan-indonesia-<jenis>-<tahun>`) and commits one mapping
  per PDF, `data/mapping/<jenis>/<id>.yaml`: `bpk_url`, `bpk_filename`, `archive_url`, `sha256`
  and `bytes` of BPK's file, `uploaded_at`, `verified_at`.
- 2026-11-28: UU and Perppu only. 1,830 of our 2,054 UU files and 64 of our 170 Perppu files
  are in it by sha256; 2,096 of its 2,115 mappings carry `verified_at`. By BPK's URL it maps
  2,052 UU and 66 Perppu files; for the other 222 UU and 2 Perppu files its sha256 is not the one
  we recorded (why was not checked), so the importer takes those from BPK.
- The importer tries a listed copy before BPK and keeps it only when its sha256 is the
  mapping's (decision 0029, `sources/dharmasastra.py`). It reads the repository as one tarball
  from `codeload.github.com`, with no API token.

## Hugging Face mirror `Azzindani/ID_REG`

- Apache-2.0. About 267,000 regulation PDFs scraped from peraturan.bpk.go.id around April 2025, in zips of about 1,000 PDFs, named with BPK's file names (spaces as `_`).
- Files checked against BPK downloads were byte-identical (3 of 3, 2026-11-21). Single files are read by HTTP range request (`remotezip`), with no Cloudflare.
- The importer falls back to it when a BPK download fails (`data/sources/mirrors/id_reg.json`). Nothing after about April 2025 is in it.
- `Azzindani/ID_REG_Parsed` (one row per pasal, no ayat, lists or Penjelasan) is only useful as a cross-check.

## peraturan.go.id (earlier imports)

- Run by the Direktorat Jenderal Peraturan Perundang-undangan, Kementerian Hukum (not "JDIH Kementerian Hukum").
- Answers only Indonesian IPs, and the block is switched on and off (2026-11-21, check-host.net from 40 locations: only Jakarta answered; it had worked from the US the evening before). `import-peraturan.yml` works only while the site lets other IPs in.
- Use HTTP/1.1; HTTP/2 got a reset once.
- Gives "01 Januari 1970" as tanggal penetapan for some laws. The importer reads it as unknown.
- About 1,900 of its PDFs were downloaded on 2026-11-20 and 21 without being kept; only their sha256 is in the manifest. BPK's copy is used instead.

## datahukum.com (compared, not imported; 2026-11-27)

- A static compilation of consolidated UU, PP, Perpres, Perma and treaties; it says it is not an official publication, and coverage is patchy (no page for UU 8/2005).
- Refuses automated fetches (403); opens in a browser.
- Its MK ruling text per pasal is word for word BPK's. Its "Riwayat" lists, per amending law, the pasal changed, added and revoked, but skips some amendments (UU 4/2009: no UU 11/2020 or Perppu 2/2022) and files a partial revocation under "Mengubah" (UU 23/2014 on UU 28/2009). Under "Mencabut" it lists only the base law of a chain.

## Other hosts (2026-11-20 and 21)

| Host | From a GitHub runner (US) | From the Claude container |
|---|---|---|
| `berkas2.dpr.go.id` | 206 for PDFs | 403 |
| `www.dpr.go.id`, `berkas.dpr.go.id/jdih` | 403 | 403 |
| `jdih.go.id`, `jdih.setkab.go.id` | time out (Indonesian IPs only) | time out |
| `jdih.esdm.go.id` | 301 | |
| `web.archive.org`, `archive.org` | 200 | connection reset |

These came from `probe-sources.yml`, removed 2026-11-24. To re-check, restore it from git history (7f6dcaed).
