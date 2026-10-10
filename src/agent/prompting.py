"""Loads `prompts/<agent>_<step>.md` at runtime and fills `{{placeholders}}`."""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

from src.models.evidence import ProductBrief

from .taxonomy import Taxonomy

PROMPT_DIR = Path(__file__).with_name("prompts")
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


@cache
def _read(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text()


def render_regions(brief: ProductBrief, regions: list[str] | None = None) -> str:
    return ", ".join(
        f"{r} (markets: {', '.join(brief.region_markets.get(r, [])) or 'n/a'})"
        for r in regions or brief.regions
    )


def render_brief(brief: ProductBrief) -> str:
    ref = brief.reference_model
    competitors = ", ".join(f"{c.name} [{', '.join(c.regions)}]" for c in brief.competitors)
    lines = [
        f"- Task: situation analysis for the **successor** of the reference model {brief.model_code} ({ref.name}), "
        f"in the regions below only",
        f"- Reference model (baseline): {brief.model_code} – {ref.brand} {ref.name}, powertrain {ref.powertrain or 'n/a'}",
        f"- Segment: {brief.segment}",
        f"- Regions: {render_regions(brief)}",
        f"- Competitors in scope (regions sold in): {competitors or 'none in the knowledge layer'}",
        f"- Focus areas: {', '.join(brief.focus_areas) or 'all'}",
    ]
    return "\n".join(lines)


def render_prompt(name: str, *, brief: ProductBrief, taxonomy: Taxonomy, **values: object) -> str:
    text = _read(name).replace("{{common_rules}}", _read("_common_rules"))
    values = {"brief": render_brief(brief), "taxonomy": taxonomy.render(), **values}

    def sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in values:
            raise KeyError(f"prompt {name!r} needs {{{{{key}}}}}")
        return str(values[key])

    return _PLACEHOLDER.sub(sub, text)
