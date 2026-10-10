"""Attribute taxonomy (AGENT_SPEC §4.3): from the ontology if it defines one, else taxonomy.yaml."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .tools.knowledge import get_backend

_YAML = Path(__file__).with_name("taxonomy.yaml")


class Taxonomy:
    def __init__(self, areas: dict[str, list[str]]) -> None:
        self.areas = {area: list(attrs) for area, attrs in areas.items()}
        self.area_of = {attr: area for area, attrs in self.areas.items() for attr in attrs}

    @property
    def attributes(self) -> list[str]:
        return list(self.area_of)

    def focus(self, focus_areas: list[str]) -> list[str]:
        """Attributes in the brief's focus areas (areas or single attributes); empty = all."""
        if not focus_areas:
            return self.attributes
        wanted = {f.strip().lower() for f in focus_areas}
        out = [a for area, attrs in self.areas.items() if area.lower() in wanted for a in attrs]
        out += [a for a in self.attributes if a.lower() in wanted and a not in out]
        return out or self.attributes

    def normalize(self, name: str) -> str:
        """Map an LLM-proposed attribute to a taxonomy key or `unmapped:<snake_case>`."""
        raw = name.strip()
        if raw.startswith("unmapped:"):
            raw = raw[len("unmapped:") :]
        key = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")
        if key in self.area_of:
            return key
        return f"unmapped:{key or 'unknown'}"

    def render(self) -> str:
        return "\n".join(f"- {area}: {', '.join(attrs)}" for area, attrs in self.areas.items())


async def load_taxonomy() -> Taxonomy:
    # ModuleBackend returns None when the optional function is absent, not when it fails.
    areas = await get_backend().get_taxonomy()
    if areas is None:
        areas = yaml.safe_load(_YAML.read_text())
    return Taxonomy(areas)
