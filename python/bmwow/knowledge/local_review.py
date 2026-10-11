"""Build an offline review form without sending source contents to a provider."""

import base64
import json
from pathlib import Path
from typing import get_args

from bmwow.ontology.models import CapabilityAvailability

from .catalog import CatalogReview, source_hash
from .manifest import CurationManifest


def render_local_review(manifest: CurationManifest, catalog: CatalogReview) -> str:
    """Embed private inputs locally; edited exports still need normal staging validation."""
    source = Path(catalog.source_file)
    if source_hash(source) != catalog.source_hash:
        raise ValueError("Catalog source changed; prepare and review the new edition")
    payload = json.dumps(
        {
            "manifest": manifest.model_dump(mode="json"),
            "catalog": catalog.model_dump(mode="json"),
            "availability": list(get_args(CapabilityAvailability)),
            "pdf": base64.b64encode(source.read_bytes()).decode("ascii"),
        },
        ensure_ascii=True,
    )
    # These characters must never turn source text into HTML or executable JavaScript.
    payload = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return (
        Path(__file__)
        .with_name("local_review.html")
        .read_text(encoding="utf-8")
        .replace("__BMWOW_REVIEW_PAYLOAD__", payload)
    )
