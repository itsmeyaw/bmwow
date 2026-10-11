"""Build the local web corpus from the approved URL list (one plain HTTP GET per URL; no crawling,
no Firecrawl, no links followed).

    uv run python -m scripts.build_web_corpus --dry-run      # show the list, download nothing
    uv run python -m scripts.build_web_corpus                # download missing pages
    uv run python -m scripts.build_web_corpus --refresh      # download all pages again

Pages go to `data/web_corpus/pages/<hash>.json` (gitignored: third-party text) with URL, title,
retrieval time, extracted text, tags and region; `data/web_corpus/manifest.json` lists every URL's
outcome. Use the corpus with SEARCH_BACKEND=corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from bmwow.agent.config import get_settings
from bmwow.agent.sources import canonical_url
from bmwow.agent.tools.html_text import html_to_text
from bmwow.agent.tools.web_corpus import CorpusPage

SOURCES = Path(__file__).resolve().parents[1] / "bmwow" / "agent" / "web_corpus_sources.yaml"
MAX_BYTES = 5_000_000
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) BMWow-hackathon-corpus/1.0 (one-time fetch of approved URLs)"
)
EU = (
    "at be bg hr cy cz dk ee fi fr de gr hu ie it lv lt lu mt nl pl pt ro sk si es se gb no ch is"
).split()
REGION_COUNTRIES = {"EU": EU, "US": ["us"], "CN": ["cn"], "GLOBAL": []}


class SourceEntry(BaseModel):
    url: str
    tags: list[str] = Field(default_factory=list)
    region: str = "GLOBAL"
    why: str = ""


def page_path(out: Path, url: str) -> Path:
    return out / "pages" / f"{hashlib.sha1(canonical_url(url).encode()).hexdigest()[:12]}.json"


def fetch(url: str) -> tuple[str, str]:
    """(content type, decoded body) of one GET."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en,de;q=0.8"}
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        ctype = response.headers.get("Content-Type", "")
        raw = response.read(MAX_BYTES + 1)[:MAX_BYTES]
        charset = response.headers.get_content_charset() or "utf-8"
    return ctype, raw.decode(charset, errors="replace")


def build(entries: list[SourceEntry], out: Path, refresh: bool) -> list[dict]:
    (out / "pages").mkdir(parents=True, exist_ok=True)
    results = []
    for e in entries:
        path = page_path(out, e.url)
        if path.exists() and not refresh:
            results.append({"url": e.url, "status": "kept", "file": path.name})
            continue
        try:
            ctype, body = fetch(e.url)
            if "html" not in ctype and "text" not in ctype:
                raise ValueError(f"unsupported content type {ctype!r} (PDF etc. not supported yet)")
            title, text = html_to_text(body) if "html" in ctype else ("", body)
            if len(text) < 300:
                raise ValueError(f"only {len(text)} characters of text (JavaScript-rendered page?)")
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            results.append(
                {"url": e.url, "status": "failed", "reason": f"{type(exc).__name__}: {exc}"}
            )
            continue
        region = e.region.upper()
        page = CorpusPage(
            url=e.url,
            title=title or e.url,
            retrieved_at=datetime.now(UTC).isoformat(),
            markdown=text,
            tags=e.tags,
            region=region,
            countries=REGION_COUNTRIES.get(region, []),
            why=e.why,
        )
        path.write_text(page.model_dump_json(indent=1), encoding="utf-8")
        results.append(
            {
                "url": e.url,
                "status": "saved",
                "file": path.name,
                "chars": len(text),
                "numbers": len(re.findall(r"\d", text)),
            }
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--sources", type=Path, default=SOURCES)
    parser.add_argument("--out", type=Path, default=None, help="default: <DATA_DIR>/web_corpus")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    entries = [
        SourceEntry.model_validate(x) for x in yaml.safe_load(args.sources.read_text()) or []
    ]
    out = args.out or get_settings().web_corpus_dir
    if args.dry_run:
        for e in entries:
            print(f"[{e.region:6}] {e.url}\n         tags: {', '.join(e.tags)} · {e.why}")
        print(f"\n{len(entries)} URLs; nothing downloaded (dry run).")
        return
    results = build(entries, out, args.refresh)
    (out / "manifest.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    for r in results:
        detail = r.get("reason") or f"{r.get('chars', '')} chars"
        print(f"{r['status']:7} {r['url']}  {detail}")
    print(
        f"\n{sum(r['status'] != 'failed' for r in results)} of {len(results)} pages available in {out}"
    )


if __name__ == "__main__":
    main()
