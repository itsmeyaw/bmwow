"""Run an analysis and review its requirement candidates at the PM gate, in the terminal.

    uv run python -m scripts.review_requirements scripts/example_request.json --demo
    uv run python -m scripts.review_requirements request.json --snapshot S --knowledge-config C \\
        --env-file ../.env

`--demo` uses the synthetic fakes only (knowledge, LLM and web): no keys, no BMW data. Without it, the
configured knowledge service and providers are used; LLM steps on BMW data still need
ALLOW_LLM_ON_INTERNAL_DATA=true. Commands at the gate:

    list                         candidates with target, intent, priority, status
    show REQ-1                   one candidate in full
    why REQ-1 [question]         reasoning from the candidate's evidence
    approve REQ-1 [reason]       / reject REQ-1 [reason]
    freeze REQ-1 [reason]        keep today's value
    cap REQ-1 520 [reason]       improve at most up to 520
    floor REQ-1 500 [reason]     reach at least 500
    set REQ-1 510 [reason]       use exactly 510
    deprio REQ-1 [reason]        not important (kept with low priority)
    say <free text>              e.g. "REQ-2 not important; REQ-1 max 520 km" (then confirm / cancel)
    confirm | cancel             apply or drop the parsed constraints
    done                         finish the review
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from bmwow.agent import service
from bmwow.agent.knowledge_bridge import configure_service, ontology, sql_client
from bmwow.agent.models.evidence import AnalysisRequest, assessment_label
from bmwow.agent.tools.knowledge import ModuleBackend, set_backend
from bmwow.knowledge import create_knowledge_service

KINDS = {"freeze": "freeze", "cap": "cap", "floor": "floor", "set": "set", "deprio": "deprioritize"}


def _target(c: dict[str, Any]) -> str:
    t = c.get("target")
    return (
        f"{t['operator']} {t['value']:g} {t['unit']} {t['condition']}".strip() if t else "to be set"
    )


def print_list(gate: dict[str, Any]) -> None:
    for c in gate["candidates"]:
        print(
            f"  {c['id']:6} {c['status']:9} prio {c['priority']:6} {c['change_intent']:9} "
            f"target {_target(c):24} {c['title']}"
        )


def print_one(c: dict[str, Any]) -> None:
    print(
        f"\n{c['id']} · {c['title']}  "
        f"[{assessment_label(c['assessment'])} → {c['change_intent']}, {c['status']}]"
    )
    print(f"  statement:  {c['statement']}")
    print(f"  value:      {c['customer_value']}")
    print(f"  target:     {_target(c)}" + (f"  ({c['target']['rule']})" if c.get("target") else ""))
    print(
        "  options:    "
        + (", ".join(f"{o['label']} {o['value']:g} {o['unit']}" for o in c["options"]) or "none")
    )
    print(f"  baseline:   {c['baseline_status']} — {c['baseline_rationale']}")
    print(
        f"  criterion:  {c['criterion']['description']} ({c['criterion']['verification_method']})"
    )
    for k in c["constraints"]:
        print(f"  constraint: {k['kind']} {k.get('value') or ''} {k.get('reason') or ''}")
    for p in c["open_points"]:
        print(f"  open:       {p}")
    print(f"  evidence:   {', '.join(c['evidence_ids'])}")


def parse(line: str) -> dict[str, Any] | str:
    """A command line → a gate action, or a local command name."""
    words = line.strip().split()
    if not words:
        return "noop"
    cmd, args = words[0].lower(), words[1:]
    if cmd in ("list", "show", "help"):
        return line.strip()
    if cmd in ("done", "confirm", "cancel"):
        return {"action": cmd}
    if cmd == "say":
        return {"action": "constrain_text", "text": line.strip()[4:]}
    if cmd == "why" and args:
        return {
            "action": "why",
            "candidate_id": args[0].upper(),
            "question": " ".join(args[1:]) or "Why?",
        }
    if cmd in ("approve", "reject") and args:
        return {"action": cmd, "candidate_id": args[0].upper(), "reason": " ".join(args[1:])}
    if cmd in KINDS and args:
        action: dict[str, Any] = {
            "action": "constrain",
            "candidate_id": args[0].upper(),
            "kind": KINDS[cmd],
        }
        rest = args[1:]
        if KINDS[cmd] in ("cap", "floor", "set"):
            if not rest:
                return f"error: {cmd} needs a value"
            action["value"] = float(rest[0])
            rest = rest[1:]
        action["reason"] = " ".join(rest)
        return action
    return f"error: unknown command {line.strip()!r} (type help)"


async def main(path: str) -> None:
    request = AnalysisRequest.model_validate(json.loads(Path(path).read_text()))
    run_id = await service.start_analysis(request, pm_gate=True)
    print(f"run {run_id}: analysing…")
    status = await service.get_analysis(run_id)
    while status.state == "running":
        await asyncio.sleep(0.2)
        status = await service.get_analysis(run_id)
    print_list(status.gate or {})
    while status.state == "waiting_for_pm":
        gate = status.gate or {}
        line = await asyncio.to_thread(input, "gate> ")
        action = parse(line)
        if isinstance(action, str):
            if action == "list":
                print_list(gate)
            elif action.startswith("show"):
                cid = action.split()[-1].upper()
                match = [c for c in gate["candidates"] if c["id"] == cid]
                print_one(match[0]) if match else print(f"unknown {cid}")
            elif action == "help":
                print(__doc__.split("Commands at the gate:", 1)[1])
            elif action != "noop":
                print(action)
            continue
        status = await service.gate_action(run_id, action)
        last = (status.gate or {}).get("last")
        if last:
            print(f"→ {last['response']}")
    if status.analysis is None:
        print(f"run {status.state}: {status.error}")
    else:
        print("\nreview finished:")
        for c in status.analysis.requirement_candidates:
            print(
                f"  {c.id:6} {c.status:9} prio {c.priority:6} target {_target(c.model_dump(mode='json')):24} {c.title}"
            )
    await service.aclose()


def _demo() -> None:
    """Synthetic fakes only: knowledge, LLM and web (python/tests/fakes)."""
    os.environ.update(KNOWLEDGE_BACKEND="fake", ALLOW_LLM_ON_INTERNAL_DATA="true")
    from bmwow.agent import llm
    from bmwow.agent.config import get_settings
    from bmwow.agent.tools import knowledge, web_search
    from tests.fakes.knowledge import FakeKnowledge
    from tests.fakes.llm import fake_models
    from tests.fakes.web import FakePageProvider

    get_settings.cache_clear()
    knowledge.set_backend(FakeKnowledge())
    web_search.set_search_backend(
        web_search.CachedSearchBackend(
            FakePageProvider(), get_settings().web_cache_dir, offline=False
        )
    )
    strong, cheap, emb, _ = fake_models()
    llm.set_overrides(strong=strong, cheap=cheap, embeddings=emb)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("request")
    parser.add_argument(
        "--demo", action="store_true", help="synthetic fakes only (no keys, no BMW data)"
    )
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--knowledge-config", type=Path)
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    if args.demo:
        _demo()
    elif args.snapshot:
        if not args.knowledge_config:
            parser.error("--snapshot and --knowledge-config must be supplied together")
        database_url = (
            dotenv_values(args.env_file).get("DATABASE_URL")
            if args.env_file
            else os.getenv("DATABASE_URL")
        )
        configure_service(
            create_knowledge_service(
                args.snapshot, args.knowledge_config, database_url=database_url
            )
        )
        set_backend(ModuleBackend(ontology, sql_client))
    asyncio.run(main(args.request))
