"""Fake knowledge backend: the real adapter (ModuleBackend) over the fake modules."""

from __future__ import annotations

from src.agent.tools.knowledge import ModuleBackend

from . import ontology, sql_client


class FakeKnowledge(ModuleBackend):
    def __init__(self) -> None:
        super().__init__(ontology, sql_client)
