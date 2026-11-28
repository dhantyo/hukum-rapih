"""archive.org copies of BPK's PDFs, listed by github.com/frenicohansen/idn-dharmasastra-archive
(CC0): one mapping file per PDF, ``data/mapping/<jenis>/<id>.yaml``, with BPK's URL of the file,
the archive.org URL of the copy and the sha256 of BPK's file. The importer reads a copy from
there before it asks BPK, and only keeps bytes whose sha256 is the mapping's (decision 0029).
"""

from __future__ import annotations

import functools
import hashlib
import io
import sys
import tarfile
from typing import NamedTuple
from urllib.parse import unquote

import httpx
import yaml

from .. import USER_AGENT
from ..yamlio import load_yaml

REPO = "frenicohansen/idn-dharmasastra-archive"
TARBALL = f"https://codeload.github.com/{REPO}/tar.gz/refs/heads/main"


class Copy(NamedTuple):
    archive_url: str
    sha256: str      # of BPK's file, as the archive downloaded it


def read_mappings(tarball: bytes) -> dict[str, Copy]:
    """BPK URL, percent-decoded -> its archive.org copy, from a tarball of the repository.
    Mappings missing a field (an upload still running) are left out."""
    out = {}
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
        for member in tar:
            name = member.name
            if not (member.isfile() and "/data/mapping/" in name and name.endswith(".yaml")):
                continue
            m = load_yaml(tar.extractfile(member).read().decode())
            if isinstance(m, dict) and m.get("bpk_url") and m.get("archive_url") and m.get("sha256"):
                out[unquote(m["bpk_url"])] = Copy(m["archive_url"], m["sha256"])
    return out


@functools.cache
def copies() -> dict[str, Copy]:
    """The mappings, read once per run; empty when GitHub cannot be read, so the importer
    goes to BPK as before."""
    try:
        r = httpx.get(TARBALL, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=60)
        r.raise_for_status()
        return read_mappings(r.content)
    except (httpx.HTTPError, tarfile.TarError, yaml.YAMLError, UnicodeDecodeError) as e:
        print(f"{REPO} not read ({type(e).__name__}: {str(e)[:120]}); BPK only", file=sys.stderr)
        return {}


def fetch(f: dict) -> tuple[bytes, str] | None:
    """The archive.org copy of the BPK file ``f`` (a ``BpkFile`` of the record) and a note
    naming it, or None: no mapping for its URL, a mapping for other bytes than the ones
    recorded, archive.org not answering, or a copy whose sha256 is not the mapping's."""
    copy = copies().get(unquote(f["url"]))
    if copy is None or f.get("sha256") not in (None, copy.sha256):
        return None
    try:
        r = httpx.get(copy.archive_url, headers={"User-Agent": USER_AGENT}, follow_redirects=True,
                      timeout=httpx.Timeout(30, read=300))
        r.raise_for_status()
    except httpx.HTTPError:
        return None
    if hashlib.sha256(r.content).hexdigest() != copy.sha256:
        return None
    return r.content, f"bytes from {copy.archive_url} ({REPO}), sha256 checked"
