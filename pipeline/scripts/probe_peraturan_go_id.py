"""Probe peraturan.go.id from GitHub Actions, read-only: whether it answers directly or which
free Indonesian proxies reach it, how complete its listing is against our records, and whether
its PDFs carry a text layer.

    uv run --with socksio python scripts/probe_peraturan_go_id.py [--sample N] [--out DIR]

peraturan.go.id answers Indonesian IPs only (docs/sources.md). The proxies come from
ProxyScrape's free list for Indonesia; TLS is always verified, nothing but public pages is
requested, requests keep the importer's 2-second spacing, a run of 403/429 answers stops the
probe, and each stage has a time budget. report.md and probe.json in DIR (default: the current
folder) are rewritten after every stage. Nothing in data/ is changed.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from hukum_rapih import USER_AGENT

DATA = HERE.parent.parent / "data"
SITE = "https://peraturan.go.id"
PROXY_LIST = ("https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies"
              "&country=id&proxy_format=protocolipport&format=text")
DELAY = 2.0              # seconds between requests, as the importer
TRIES = 4                # proxies tried per request before giving up on it
BLOCKED_IN_A_ROW = 5     # 403/429 answers in a row that stop the probe
STAGE_MINUTES = 25       # time budget of each listing walk and of the PDF sample


def reaches(proxy: str | None) -> float | None:
    """Seconds the site's front page took through ``proxy`` (None: directly), or None."""
    start = time.monotonic()
    try:
        with httpx.Client(proxy=proxy, timeout=12, verify=True, http2=False,
                          headers={"User-Agent": USER_AGENT}) as c:
            r = c.get(SITE + "/")
        return time.monotonic() - start if r.status_code == 200 and "peraturan" in r.text.lower() else None
    except Exception:  # noqa: BLE001 - a dead proxy is the common case
        return None


class Blocked(RuntimeError):
    """The site answered 403 or 429 BLOCKED_IN_A_ROW times: stop before it bans us."""


class Rotating:
    """GETs through the working proxies (None: directly), fastest first, at most TRIES of them
    per request, DELAY apart; a run of 403/429 answers stops the probe."""

    def __init__(self, proxies: list[str | None]):
        self.proxies, self.i, self.last, self.refused = proxies, 0, 0.0, 0

    def get(self, path: str) -> httpx.Response | None:
        for _ in range(min(TRIES, len(self.proxies))):
            wait = DELAY - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            proxy = self.proxies[self.i % len(self.proxies)]
            try:
                with httpx.Client(proxy=proxy, timeout=httpx.Timeout(15, read=40), verify=True,
                                  http2=False, follow_redirects=True,
                                  headers={"User-Agent": USER_AGENT}) as c:
                    r = c.get(SITE + path if path.startswith("/") else path)
                if r.status_code == 200:
                    self.refused = 0
                    return r
                if r.status_code in (403, 429):
                    self.refused += 1
                    if self.refused >= BLOCKED_IN_A_ROW:
                        raise Blocked(f"{r.status_code} {BLOCKED_IN_A_ROW} times in a row, last on {path}")
            except httpx.HTTPError as e:
                print(f"{proxy or 'direct'} failed on {path}: {type(e).__name__}", file=sys.stderr)
            self.i += 1
        return None


def listing(client: Rotating, jenis: str) -> tuple[set[str], int, bool]:
    """Ids on the site's listing of ``jenis``, pages read, and whether the walk finished."""
    ids, page, until = set(), 1, time.monotonic() + STAGE_MINUTES * 60
    while time.monotonic() < until:
        r = client.get(f"/{jenis}?page={page}")
        if r is None:
            return ids, page - 1, False
        found = re.findall(rf'href="/id/{jenis}-no-([0-9a-z]+)-tahun-(\d{{4}})"', r.text)
        if not found:
            return ids, page - 1, True
        ids |= {f"{jenis}_{n}_{y}" for n, y in found}
        page += 1
    return ids, page - 1, False


def ours(jenis: str) -> dict[str, dict]:
    out = {}
    for p in (DATA / "peraturan" / jenis).glob("*/*/*.yaml"):
        out[p.stem] = yaml.safe_load(p.read_text())
    return out


def known_hashes() -> set[str]:
    path = DATA / "sources" / "manifests" / "peraturan.go.id.jsonl"
    return {json.loads(line)["sha256"] for line in path.read_text().splitlines() if line.strip()}


def text_layer(pdf: bytes) -> tuple[int, float]:
    """Pages, and characters of text per page in the PDF's own text layer (no OCR)."""
    import pymupdf

    doc = pymupdf.open(stream=pdf, filetype="pdf")
    chars = sum(len(page.get_text().strip()) for page in doc)
    return doc.page_count, chars / max(doc.page_count, 1)


def sample_pdfs(client: Rotating, records: dict[str, dict], ids: list[str]) -> list[dict]:
    hashes, rows, until = known_hashes(), [], time.monotonic() + STAGE_MINUTES * 60
    for law in ids:
        if time.monotonic() > until:
            break
        jenis, nomor, tahun = law.split("_")
        r = client.get(f"/id/{jenis}-no-{nomor}-tahun-{tahun}")
        pdf = re.search(r'href="(/files/[^"]+\.pdf)"', r.text, re.IGNORECASE) if r else None
        got = client.get(pdf[1]) if pdf else None
        row = {"id": law, "bpk_ocr": bool(_text_version(records[law]).get("ocr"))}
        if got is None or not got.content.startswith(b"%PDF"):
            row["pdf"] = "not reached" if r is None else ("no PDF link" if not pdf else "download failed")
        else:
            pages, per_page = text_layer(got.content)
            sha = hashlib.sha256(got.content).hexdigest()
            row |= {"pdf": pdf[1], "pages": pages, "chars_per_page": round(per_page),
                    "sha256_known": sha in hashes}
        rows.append(row)
    return rows


def _text_version(rec: dict) -> dict:
    return next((v for v in rec.get("versions") or [] if v.get("text")), {})


def main(argv: list[str]) -> int:
    sample = int(argv[argv.index("--sample") + 1]) if "--sample" in argv else 20
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else Path(".")
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {}
    lines = ["# peraturan.go.id from GitHub Actions", ""]

    def write() -> None:            # after every stage, so a cancelled run still reports
        (out / "report.md").write_text("\n".join(lines) + "\n")
        (out / "probe.json").write_text(json.dumps(report, indent=1))
        print("\n".join(lines), flush=True)

    direct = reaches(None)
    report["direct_seconds"] = direct
    lines.append(f"Direct, no proxy: {'reached in %.1f s' % direct if direct else 'not reached'}")
    if direct:
        route: list[str | None] = [None]
    else:
        listed = [p.strip() for p in httpx.get(PROXY_LIST, timeout=30).text.splitlines() if "://" in p]
        with ThreadPoolExecutor(40) as pool:
            timed = list(zip(listed, pool.map(reaches, listed)))
        route = [p for p, _ in sorted((x for x in timed if x[1] is not None), key=lambda x: x[1])]
        report |= {"proxies_listed": len(listed), "proxies_working": route,
                   "working_by_protocol": {k: sum(p.startswith(k) for p in route) for k in ("http", "socks4", "socks5")}}
        lines.append(f"Proxies listed: {len(listed)}; reaching the site: {len(route)} "
                     f"{report['working_by_protocol']}")
    lines.append("")
    write()
    if not route:
        return 1

    client = Rotating(route)
    try:
        lines += ["| Type | On the site | Ours | Both | Only the site | Only ours | Pages read | Walk complete |",
                  "|---|---:|---:|---:|---:|---:|---:|---|"]
        records: dict[str, dict] = {}
        for jenis in ("uu", "perppu"):
            site, pages, complete = listing(client, jenis)
            mine = ours(jenis)
            records |= mine
            report[jenis] = {"site": len(site), "ours": len(mine), "both": len(site & set(mine)),
                             "only_site": sorted(site - set(mine)), "only_ours": sorted(set(mine) - site),
                             "pages": pages, "complete": complete}
            lines.append(f"| {jenis} | {len(site)} | {len(mine)} | {len(site & set(mine))} | "
                         f"{len(site - set(mine))} | {len(set(mine) - site)} | {pages} | {complete} |")
            write()

        ocr = [k for k, r in records.items() if _text_version(r).get("ocr")]
        typed = [k for k, r in records.items() if _text_version(r) and not _text_version(r).get("ocr")]
        random.seed(20261128)
        picked = (random.sample(ocr, min(sample * 3 // 4, len(ocr)))
                  + random.sample(typed, min(sample // 4, len(typed))))
        rows = sample_pdfs(client, records, picked)
        report["sample"] = rows
        lines += ["", "## Sample PDFs (mostly laws whose BPK text needed OCR)", "",
                  "| Law | BPK text OCR'd | PDF | Pages | Text chars per page | sha256 already in our manifest |",
                  "|---|---|---|---:|---:|---|"]
        lines += [f"| {r['id']} | {r['bpk_ocr']} | {r['pdf']} | {r.get('pages', '')} | "
                  f"{r.get('chars_per_page', '')} | {r.get('sha256_known', '')} |" for r in rows]
    except Blocked as e:
        lines += ["", f"Stopped: the site refused us ({e})."]
        report["blocked"] = str(e)
    write()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
