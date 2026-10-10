"""`resolve_request`: AnalysisRequest → ProductBrief (AGENT_SPEC §3.1).

Deterministic, no LLM. The PM gives only a model code and optionally regions (none = all regions the
model has data for); everything else (segment, powertrain, competitors, markets, search locales) comes
from the registry and the knowledge layer.
"""

from __future__ import annotations

from src.models.evidence import AnalysisRequest, ProductBrief
from src.models.knowledge import ModelNode

from . import router
from .registry import Registry, ResolveError, load_registry


def tag_regions(model: ModelNode, regions: list[str]) -> ModelNode:
    """Use curated availability when present; retain the legacy v1 fallback for old records."""
    if model.curation_note is not None or model.sold_regions:
        sold_in = [r for r in regions if r in {x.upper() for x in model.sold_regions}]
    else:
        sold_in = (
            [r for r in regions if r in {x.upper() for x in model.regions}]
            if model.regions
            else list(regions)
        )
    return model.model_copy(update={"regions": sold_in})


async def _competitors(segment: str, regions: list[str]) -> list[ModelNode]:
    found: dict[str, ModelNode] = {}
    for model in (await router.fetch("competitor_models", segment, regions)).data:
        tagged = tag_regions(model, regions)
        if tagged.regions:  # never keep a competitor that is sold in none of the requested regions
            found.setdefault(model.node_id, tagged)
    return list(found.values())


async def resolve_request(
    request: AnalysisRequest, registry: Registry | None = None
) -> ProductBrief:
    registry = registry or await load_registry()
    code, regions = registry.check(request)
    reference = (await router.fetch("model", code)).data
    if reference is None:
        raise ResolveError(
            f"{code} is in the model registry but the knowledge layer has no record for it"
        )
    reference = reference.model_copy(update={"model_code": reference.model_code or code})

    region_markets = {r: list(registry.regions[r].markets) for r in regions}
    warnings: list[str] = []
    competitors = await _competitors(reference.segment, regions)
    if not competitors:
        warnings.append(
            "no competitors in the knowledge layer for this segment and these regions; "
            "competition_agent will discover them on the web"
        )
    return ProductBrief(
        reference_model=reference,
        regions=regions,
        markets=list(dict.fromkeys(m for r in regions for m in region_markets[r])),
        segment=reference.segment,
        competitors=competitors,
        search_locale={r: registry.regions[r].search for r in regions},
        region_markets=region_markets,
        warnings=warnings,
    )


async def check_brief(
    request: AnalysisRequest, brief: ProductBrief, registry: Registry | None = None
) -> None:
    """Validate a PM-corrected brief (service.start_analysis(brief_override=...)) against the registry."""
    registry = registry or await load_registry()
    code, _ = registry.check(request.model_copy(update={"regions": brief.regions}))
    registry.check(AnalysisRequest(model_code=brief.model_code, regions=brief.regions))
    if brief.model_code.upper() != code:
        raise ResolveError(f"brief is for {brief.model_code}, request is for {code}")
    missing = [
        r for r in brief.regions if r not in brief.search_locale or r not in brief.region_markets
    ]
    if missing:
        raise ResolveError(
            f"brief has no search locale or markets for region(s) {', '.join(missing)}"
        )
