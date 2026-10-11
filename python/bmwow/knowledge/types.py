"""Shared knowledge-consumer definitions; ontology vocabulary stays in ontology.models."""

from typing import Literal

from pydantic import BaseModel

MappingStatus = Literal["proposed", "reviewed"]


class SearchLocale(BaseModel):
    """Research locale policy, independent of a source's observed country population."""

    country: str
    lang: str
