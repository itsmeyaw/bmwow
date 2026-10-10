"""Model registry (§4.5) and region list (§4.4), and the request checks built on them (§3.1).

Both come from the knowledge layer when it offers `list_supported_models()` / `list_regions()`;
otherwise from `models.yaml` / `regions.yaml` next to this file. Backend errors propagate;
empty responses remain authoritative. Only None signals an unavailable optional contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from src.models.evidence import AnalysisRequest, SearchLocale, SupportedModel

from .tools.knowledge import get_backend

_MODELS_YAML = Path(__file__).with_name("models.yaml")
_REGIONS_YAML = Path(__file__).with_name("regions.yaml")


class ResolveError(ValueError):
    """The request cannot be resolved (unknown model, unknown region, unsupported combination, ...)."""


class Region(BaseModel):
    code: str
    markets: list[str]
    search: SearchLocale


@dataclass(frozen=True)
class Registry:
    models: dict[str, SupportedModel]
    regions: dict[str, Region]

    def check(self, request: AnalysisRequest) -> tuple[str, list[str]]:
        """Fail fast on input the registry does not support. Returns (model_code, regions), normalized."""
        code = request.model_code.strip().upper()
        model = self.models.get(code)
        if model is None:
            raise ResolveError(
                f"unknown model code {request.model_code!r}; valid codes: {', '.join(self.models)}"
            )
        if not request.regions:  # no regions given = all regions the model has data for
            return code, [r for r in model.regions if r in self.regions]
        regions = list(dict.fromkeys(r.strip().upper() for r in request.regions))
        unknown = [r for r in regions if r not in self.regions]
        if unknown:
            raise ResolveError(
                f"unknown region(s) {', '.join(unknown)}; valid regions: {', '.join(self.regions)}"
            )
        unsupported = [r for r in regions if r not in model.regions]
        if unsupported:
            raise ResolveError(
                f"{code} ({model.name}) has no data for region(s) {', '.join(unsupported)}; "
                f"it supports: {', '.join(model.regions)}"
            )
        return code, regions


def _models(raw: Any) -> dict[str, SupportedModel]:
    if isinstance(raw, dict):  # yaml shape: {code: {name, regions}}
        raw = [{"model_code": code, **entry} for code, entry in raw.items()]
    out = {}
    for entry in raw:
        model = SupportedModel.model_validate(entry if isinstance(entry, dict) else vars(entry))
        model.model_code = model.model_code.upper()
        model.regions = [r.upper() for r in model.regions]
        out[model.model_code] = model
    return out


def _regions(raw: dict[str, Any]) -> dict[str, Region]:
    return {
        code.upper(): Region.model_validate({"code": code.upper(), **entry})
        for code, entry in raw.items()
    }


async def load_registry() -> Registry:
    backend = get_backend()
    models = await backend.list_supported_models()
    regions = await backend.list_regions()
    return Registry(
        models=_models(yaml.safe_load(_MODELS_YAML.read_text()) if models is None else models),
        regions=_regions(yaml.safe_load(_REGIONS_YAML.read_text()) if regions is None else regions),
    )
