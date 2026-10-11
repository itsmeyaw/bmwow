"""Render a saved SituationAnalysis as one self-contained HTML report (no external assets).

    uv run python -m scripts.visualize_analysis ../data/processed/analyses/<run_id>.json
    # → ../data/processed/reports/<run_id>.html (gitignored, like the analysis itself)

Sections: run overview and data availability; customer shares per feature with 95% intervals by
region (filter: problem / request / praise); what exactly customers mean (sub-themes + judgment) for
the selected feature; competitor values vs ours; judgments, requirement candidates and trends as tables.
Every chart has a table view. The report contains BMW-derived data: keep it local.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bmwow.agent.models.evidence import SituationAnalysis, assessment_label

MAX_FEATURES = 14
MAX_REGIONS = 3  # categorical slots validated all-pairs; more regions fold into the table view


def build_data(a: SituationAnalysis) -> dict:
    findings = {f.id: f for r in a.reports.values() for f in r.findings}
    regions = [r for r in a.brief.regions][:MAX_REGIONS]
    packages = []
    for p in a.evidence_packages:
        customers = [
            {
                "direction": s.direction,
                "region": s.region or "All",
                "share": s.share,
                "k": s.k,
                "n": s.n,
                "lo": s.ci_low,
                "hi": s.ci_high,
                "thin": s.thin,
                "differs": s.differs_from,
                "p": s.p_value,
                "id": s.finding_id,
            }
            for s in p.customers
        ]
        comps = []
        for v in p.competitor_values:
            dots = []
            for fid in v.finding_ids:
                f = findings.get(fid)
                if f is not None and f.quantity is not None:
                    variant = next(
                        (
                            x.strip()[8:]
                            for x in f.quantity.qualifier.split(";")
                            if x.strip().lower().startswith("variant ")
                        ),
                        "",
                    )
                    dots.append(
                        {
                            "subject": f.subject,
                            "value": f.quantity.value,
                            "variant": variant,
                            "id": fid,
                        }
                    )
            comps.append(
                {
                    "unit": v.unit,
                    "condition": v.condition,
                    "region": v.region,
                    "n": v.n,
                    "min": v.minimum,
                    "median": v.median,
                    "max": v.maximum,
                    "ours": v.ours,
                    "rank": v.ours_rank,
                    "size": v.field_size,
                    "lower": v.lower_is_better,
                    "dots": dots,
                }
            )
        packages.append(
            {
                "attribute": p.attribute,
                "label": p.label,
                "importance": p.importance,
                "customers": customers,
                "sub_themes": [
                    {
                        "direction": t.direction,
                        "name": t.name,
                        "k": t.k,
                        "of": t.of,
                        "method": t.method,
                    }
                    for t in p.sub_themes
                ],
                "competitors": comps,
                "coverage": p.coverage,
            }
        )
    assessments = {
        x.attribute: {
            "assessment": x.assessment,
            "assessment_label": assessment_label(x.assessment),
            "what": x.what_exactly,
            "widespread": x.widespread,
            "certainty": x.certainty,
            "guard": x.guard_status,
            "note": x.note,
            "reasoning": x.reasoning,
        }
        for x in a.feature_assessments
    }
    candidates = [
        {
            "id": c.id,
            "title": c.title,
            "assessment": c.assessment,
            "assessment_label": assessment_label(c.assessment),
            "intent": c.change_intent,
            "baseline": c.baseline_status,
            "target": (
                f"{c.target.operator} {c.target.value:g} {c.target.unit} {c.target.condition}".strip()
                if c.target
                else "to be set by the PM"
            ),
            "statement": c.statement,
            "status": c.status,
            "priority": c.priority,
            "open": c.open_points,
        }
        for c in a.requirement_candidates
    ]
    reports = [
        {
            "agent": r.agent,
            "status": r.status,
            "findings": len(r.findings),
            "errors": len(r.errors),
            "availability": [
                {"source": x.source, "status": x.status, "reason": x.reason} for x in r.availability
            ],
        }
        for r in a.reports.values()
    ]
    trends = [
        {
            "attribute": f.attribute,
            "claim": f.claim,
            "horizon": f.horizon,
            "direction": f.direction,
            "sources": f.n_independent_sources,
        }
        for f in a.reports["trends"].findings
    ]
    fb = a.reports["feedback"].stats
    return {
        "title": f"{a.brief.model_code} · {a.brief.reference_model.name}",
        "run_id": a.run_id,
        "created": a.created_at.strftime("%Y-%m-%d %H:%M UTC"),
        "regions": regions,
        "all_regions": a.brief.regions,
        "tiles": {
            "Feedback items": int(fb.get("n_items", 0)),
            "Features with evidence": len(a.evidence_packages),
            "Judged features": sum(
                1 for x in a.feature_assessments if x.assessment != "not_assessed"
            ),
            "Requirement candidates": len(a.requirement_candidates),
        },
        "region_items": {r: int(fb.get(f"n_items:{r}", 0)) for r in a.brief.regions},
        "reports": reports,
        "packages": packages[: MAX_FEATURES * 3],
        "assessments": assessments,
        "candidates": candidates,
        "trends": trends,
    }


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Situation analysis report</title>
<style>
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;
--good:#0ca30c;--warn:#fab219;--crit:#d03b3b;--wash:rgba(42,120,214,.10)}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--page:#0d0d0d;
--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;
--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--wash:rgba(57,135,229,.14)}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;
--muted:#898781;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;
--wash:rgba(57,135,229,.14)}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);
font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:0 0 4px}.sub{color:var(--ink2);margin:0 0 16px}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:16px;margin:16px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.tile{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:12px 14px}
.tile b{display:block;font-size:26px;font-weight:600}.tile span{color:var(--ink2)}
.agents{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.st{font-weight:600}.st.ok::before{content:"✓ ";color:var(--good)}.st.partial::before{content:"◐ ";color:var(--warn)}
.st.failed::before{content:"✕ ";color:var(--crit)}.st.unavailable::before{content:"✕ ";color:var(--crit)}
.small{font-size:12px;color:var(--ink2)}.avail{margin:6px 0 0;padding:0;list-style:none}
.avail li{font-size:12px;color:var(--ink2);margin:2px 0}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 12px}
.seg button{font:inherit;border:1px solid var(--ring);background:var(--surface);color:var(--ink);padding:5px 12px;cursor:pointer}
.seg button:first-child{border-radius:8px 0 0 8px}.seg button:last-child{border-radius:0 8px 8px 0}
.seg button[aria-pressed="true"]{background:var(--wash);font-weight:600}
select{font:inherit;padding:4px 8px;border-radius:8px;border:1px solid var(--ring);background:var(--surface);color:var(--ink)}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--ink2);margin:4px 0 8px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:-1px}
.legend i.hollow{background:transparent!important;border:2px solid var(--ink2)}
svg{display:block;width:100%;height:auto;overflow:visible}svg text{fill:var(--ink2);font-size:12px}
svg .lbl{fill:var(--ink)}svg .hit{fill:transparent;cursor:default}svg .hit:focus{outline:none}
svg .grid{stroke:var(--grid);stroke-width:1}svg .base{stroke:var(--axis);stroke-width:1}
.row-sel{fill:var(--wash)}
#tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--ring);
border-radius:8px;padding:8px 10px;font-size:12px;box-shadow:0 4px 16px rgba(0,0,0,.12);display:none;max-width:280px;z-index:9}
#tip b{font-size:14px;display:block}#tip .k{display:inline-block;width:12px;height:2px;margin-right:6px;vertical-align:3px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--grid);vertical-align:top}
th{color:var(--ink2);font-weight:600}td.num{font-variant-numeric:tabular-nums;text-align:right}
details{margin-top:10px}summary{cursor:pointer;color:var(--ink2);font-size:13px}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;border:1px solid var(--ring);font-size:12px}
.what{margin:8px 0;padding:10px 12px;border-left:2px solid var(--axis);background:var(--page);border-radius:4px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media (max-width:760px){.two{grid-template-columns:1fr}}
.theme{float:right}.theme button{font:inherit;font-size:12px;border:1px solid var(--ring);background:var(--surface);color:var(--ink2);border-radius:8px;padding:3px 8px;cursor:pointer}
</style></head><body><main>
<div class="theme"><button id="themeBtn" type="button">Toggle theme</button></div>
<h1 id="title"></h1><p class="sub" id="subtitle"></p>
<div class="tiles" id="tiles"></div>
<section class="card"><h2>Agents and data availability</h2>
<p class="small">What each agent could use in this run. Missing data is reported here, not hidden.</p>
<div class="agents" id="agents"></div></section>
<section class="card"><h2>Where customers report it</h2>
<p class="small">Share of feedback items per feature and region, with 95% intervals. Features ranked by the
lower interval bound of problem/request shares. Select a row for details below.</p>
<div class="filters"><div class="seg" role="group" aria-label="Direction" id="dirSeg"></div></div>
<div class="legend" id="legend"></div>
<div id="dotChart"></div>
<details><summary>Table view</summary><div id="dotTable"></div></details></section>
<section class="card"><div class="filters"><h2 style="margin:0">What exactly customers mean</h2>
<select id="featSel" aria-label="Feature"></select></div>
<div class="two"><div><div id="judgment"></div></div><div><div id="subChart"></div>
<details><summary>Table view</summary><div id="subTable"></div></details></div></div></section>
<section class="card"><h2>Competitor values vs ours</h2>
<p class="small">Comparable values only (same unit, test standard and region). Bar = competitor range,
tick = median, dots = competitors, diamond = ours.</p><div id="compChart"></div>
<details><summary>Table view</summary><div id="compTable"></div></details></section>
<section class="card"><h2>Requirement candidates</h2><div id="cands"></div></section>
<section class="card"><h2>Judgments per feature</h2><div id="judgTable"></div></section>
<section class="card"><h2>Trends</h2><div id="trends"></div></section>
<p class="small" id="foot"></p>
</main><div id="tip" role="tooltip"></div>
<script type="application/json" id="data">__DATA__</script>
<script>
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const SERIES = ["var(--s1)", "var(--s2)", "var(--s3)"];
const NS = "http://www.w3.org/2000/svg";
const $ = id => document.getElementById(id);
const el = (tag, attrs = {}, text) => { const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); if (text != null) e.textContent = text; return e; };
const sv = (tag, attrs = {}, text) => { const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); if (text != null) e.textContent = text; return e; };
const pct = v => (v * 100).toFixed(v < 0.1 ? 1 : 0) + "%";
const fmt = v => Number(v).toLocaleString("en-US", {maximumFractionDigits: 2});
let dir = "problem", sel = null;

// theme toggle (wins both ways over the OS setting)
$("themeBtn").onclick = () => { const r = document.documentElement;
  const dark = r.dataset.theme ? r.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  r.dataset.theme = dark ? "light" : "dark"; };

// tooltip: values lead, labels follow; same on hover and keyboard focus
const tip = $("tip");
function showTip(evt, rows) { tip.replaceChildren(); for (const [value, label, color] of rows) {
  const b = el("b", {}, value); tip.append(b); const s = el("div");
  if (color) { const k = el("span", {class: "k"}); k.style.background = color; s.append(k); }
  s.append(document.createTextNode(label)); tip.append(s); }
  const r = evt.target.getBoundingClientRect(); const x = evt.clientX ?? (r.left + r.width / 2);
  const y = evt.clientY ?? r.top; tip.style.display = "block";
  tip.style.left = Math.min(x + 12, innerWidth - 290) + "px"; tip.style.top = (y + 14) + "px"; }
const hideTip = () => { tip.style.display = "none"; };
function hover(node, rows) { node.setAttribute("tabindex", "0");
  node.addEventListener("pointermove", e => showTip(e, rows)); node.addEventListener("pointerleave", hideTip);
  node.addEventListener("focus", e => showTip(e, rows)); node.addEventListener("blur", hideTip); }

function table(cols, rows) { const t = el("table"); const h = el("tr");
  for (const c of cols) h.append(el("th", {}, c.label)); t.append(h);
  for (const r of rows) { const tr = el("tr"); for (const c of cols) {
    tr.append(el("td", c.num ? {class: "num"} : {}, c.get(r))); } t.append(tr); } return t; }

// header + tiles + agents
$("title").textContent = "Situation analysis · " + D.title;
$("subtitle").textContent = `Regions ${D.all_regions.join(", ")} · run ${D.run_id} · ${D.created}`;
for (const [k, v] of Object.entries(D.tiles)) { const t = el("div", {class: "tile"});
  t.append(el("b", {}, fmt(v)), el("span", {}, k)); $("tiles").append(t); }
const regionItems = Object.entries(D.region_items).map(([r, n]) => `${r}: ${fmt(n)}`).join(" · ");
for (const r of D.reports) { const c = el("div", {class: "tile"});
  c.append(el("div", {class: "st " + r.status}, `${r.agent} — ${r.status}`),
    el("div", {class: "small"}, `${r.findings} findings` + (r.errors ? ` · ${r.errors} error(s)` : "") +
      (r.agent === "feedback" ? ` · items ${regionItems}` : "")));
  const ul = el("ul", {class: "avail"});
  for (const a of r.availability) if (a.status !== "ok")
    ul.append(el("li", {}, `${a.status === "unavailable" ? "✕" : "◐"} ${a.source}: ${a.reason || a.status}`));
  c.append(ul); $("agents").append(c); }

// direction filter (one row, above the chart it scopes)
for (const [d, label] of [["problem", "Problems"], ["request", "Requests"], ["strength", "Praise"]]) {
  const b = el("button", {type: "button", "aria-pressed": String(d === dir)}, label);
  b.onclick = () => { dir = d; for (const x of $("dirSeg").children) x.setAttribute("aria-pressed", String(x === b)); drawDots(); };
  $("dirSeg").append(b); }
const lg = $("legend");
D.regions.forEach((r, i) => { const s = el("span"); const k = el("i"); k.style.background = SERIES[i]; s.append(k, document.createTextNode(r)); lg.append(s); });
{ const s = el("span"); s.append(el("i", {class: "hollow"}), document.createTextNode("hollow = small sample")); lg.append(s); }
{ const s = el("span", {}, "line = 95% interval"); lg.append(s); }

function featureRows() {
  return D.packages.filter(p => p.customers.some(c => c.direction === dir && D.regions.includes(c.region)))
    .sort((a, b) => Math.max(...b.customers.filter(c => c.direction === dir).map(c => c.lo))
                  - Math.max(...a.customers.filter(c => c.direction === dir).map(c => c.lo)))
    .slice(0, 14); }

function drawDots() {
  const rows = featureRows(); const host = $("dotChart"); host.replaceChildren();
  if (!rows.length) { host.append(el("p", {class: "small"}, "No customer evidence in this direction.")); $("dotTable").replaceChildren(); return; }
  const W = 1000, left = 250, right = 30, top = 8, rowH = 34, H = top + rows.length * rowH + 30;
  const max = Math.min(1, Math.max(...rows.flatMap(p => p.customers.filter(c => c.direction === dir).map(c => c.hi))) * 1.08);
  const x = v => left + (v / max) * (W - left - right);
  const svg = sv("svg", {viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Customer shares by feature and region"});
  const step = max > 0.3 ? 0.1 : max > 0.12 ? 0.05 : 0.02;
  for (let t = 0; t <= max + 1e-9; t += step) { svg.append(sv("line", {class: "grid", x1: x(t), x2: x(t), y1: top, y2: H - 26}),
    sv("text", {x: x(t), y: H - 8, "text-anchor": "middle"}, pct(t))); }
  rows.forEach((p, i) => { const y0 = top + i * rowH;
    if (sel === p.attribute) svg.append(sv("rect", {class: "row-sel", x: 0, y: y0, width: W, height: rowH, rx: 6}));
    svg.append(sv("text", {class: "lbl", x: left - 12, y: y0 + rowH / 2 + 4, "text-anchor": "end"}, p.label));
    const hit = sv("rect", {class: "hit", x: 0, y: y0, width: W, height: rowH, "aria-label": p.label});
    hit.addEventListener("click", () => select(p.attribute)); hit.addEventListener("keydown", e => { if (e.key === "Enter") select(p.attribute); });
    const pts = D.regions.map((r, j) => [p.customers.find(c => c.direction === dir && c.region === r), j]).filter(([c]) => c);
    hover(hit, pts.map(([c, j]) => [`${pct(c.share)} (${c.k} of ${fmt(c.n)})`,
      `${D.regions[j]} · CI ${pct(c.lo)}–${pct(c.hi)}${c.thin ? " · small sample" : ""}${c.differs ? " · differs from " + c.differs : ""}`, SERIES[j]]));
    pts.forEach(([c, j]) => { const y = y0 + rowH / 2 + (j - (D.regions.length - 1) / 2) * 9;
      svg.append(sv("line", {x1: x(c.lo), x2: x(c.hi), y1: y, y2: y, stroke: SERIES[j], "stroke-width": 2, "stroke-linecap": "round"}));
      svg.append(sv("circle", {cx: x(c.share), cy: y, r: 5, fill: c.thin ? "var(--surface)" : SERIES[j],
        stroke: c.thin ? SERIES[j] : "var(--surface)", "stroke-width": 2})); });
    svg.append(hit); });
  svg.append(sv("line", {class: "base", x1: left, x2: left, y1: top, y2: H - 26}));
  host.append(svg);
  const trs = rows.flatMap(p => p.customers.filter(c => c.direction === dir).map(c => ({p, c})));
  $("dotTable").replaceChildren(table([
    {label: "Feature", get: r => r.p.label}, {label: "Region", get: r => r.c.region},
    {label: "Share", num: 1, get: r => pct(r.c.share)}, {label: "k / n", num: 1, get: r => `${r.c.k} / ${fmt(r.c.n)}`},
    {label: "95% CI", num: 1, get: r => `${pct(r.c.lo)}–${pct(r.c.hi)}`},
    {label: "Note", get: r => [r.c.thin ? "small sample" : "", r.c.differs ? "differs from " + r.c.differs : ""].filter(Boolean).join("; ")}], trs)); }

// feature detail: judgment + sub-themes
const fs = $("featSel");
for (const p of D.packages) fs.append(el("option", {value: p.attribute}, p.label));
fs.onchange = () => select(fs.value);
function select(attr) { sel = attr; fs.value = attr; drawDots(); drawDetail(); }
function drawDetail() {
  const p = D.packages.find(x => x.attribute === sel); const j = D.assessments[sel] || {};
  const box = $("judgment"); box.replaceChildren();
  box.append(el("div", {}, ""), el("span", {class: "pill"}, `assessment: ${j.assessment_label || "–"}`), document.createTextNode(" "),
    el("span", {class: "pill"}, `widespread: ${j.widespread || "–"}`), document.createTextNode(" "),
    el("span", {class: "pill"}, `certainty: ${j.certainty || "–"}`), document.createTextNode(" "),
    el("span", {class: "pill"}, `guard: ${j.guard || "–"}`));
  if (j.what) box.append(el("div", {class: "what"}, j.what));
  if (j.note) box.append(el("p", {class: "small"}, j.note));
  if (j.reasoning) { const d = el("details"); d.append(el("summary", {}, "Reasoning (with cited evidence ids)"), el("p", {class: "small"}, j.reasoning)); box.append(d); }
  if (p && p.coverage.length) box.append(el("p", {class: "small"}, "Coverage: " + p.coverage.filter(c => c.startsWith("missing")).join("; ")));
  const host = $("subChart"); host.replaceChildren();
  const ts = (p ? p.sub_themes : []).filter(t => t.direction === dir).sort((a, b) => b.k - a.k).slice(0, 8);
  if (!ts.length) { host.append(el("p", {class: "small"}, "No sub-themes in this direction.")); $("subTable").replaceChildren(); return; }
  const W = 520, left = 210, right = 70, rowH = 30, H = ts.length * rowH + 8, max = Math.max(...ts.map(t => t.k));
  const x = v => (v / max) * (W - left - right);
  const svg = sv("svg", {viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Sub-themes"});
  ts.forEach((t, i) => { const y = 4 + i * rowH, h = 18, w = Math.max(2, x(t.k));
    const name = t.name.length > 30 ? t.name.slice(0, 29) + "…" : t.name;
    svg.append(sv("text", {class: "lbl", x: left - 10, y: y + h / 2 + 4, "text-anchor": "end"}, name));
    svg.append(sv("path", {d: `M${left},${y} h${w - 4} a4,4 0 0 1 4,4 v${h - 8} a4,4 0 0 1 -4,4 h${-(w - 4)} z`, fill: "var(--s1)"}));
    svg.append(sv("text", {x: left + w + 6, y: y + h / 2 + 4}, `${t.k} of ${t.of}`));
    const hit = sv("rect", {class: "hit", x: 0, y: y - 6, width: W, height: rowH});
    hover(hit, [[`${t.k} of ${t.of} items`, t.name + (t.method === "llm" ? " (grouped by LLM, in a sample)" : ""), "var(--s1)"]]); svg.append(hit); });
  svg.append(sv("line", {class: "base", x1: left, x2: left, y1: 0, y2: H}));
  host.append(svg);
  $("subTable").replaceChildren(table([{label: "Sub-theme", get: t => t.name}, {label: "Items", num: 1, get: t => `${t.k} of ${t.of}`},
    {label: "Method", get: t => t.method}], ts)); }

// competitors vs ours: one small strip per comparable group
function drawComp() {
  const host = $("compChart"); const groups = D.packages.flatMap(p => p.competitors.map(c => ({p, c})));
  if (!groups.length) { host.append(el("p", {class: "small"}, "No comparable competitor values in this run.")); return; }
  for (const {p, c} of groups) { const W = 1000, left = 250, right = 40, H = 54;
    const vals = [c.min, c.max, ...(c.ours != null ? [c.ours] : [])]; let lo = Math.min(...vals), hi = Math.max(...vals);
    const pad = (hi - lo || Math.abs(hi) || 1) * 0.12; lo -= pad; hi += pad; const x = v => left + (v - lo) / (hi - lo) * (W - left - right);
    const svg = sv("svg", {viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `${p.label} competitor values`});
    const clip = (t, n) => t.length > n ? t.slice(0, n - 1) + "…" : t;
    svg.append(sv("text", {class: "lbl", x: left - 12, y: 22, "text-anchor": "end"}, clip(p.label, 32)));
    const meta = `${c.unit}${c.condition ? " · " + c.condition : ""}${c.region ? " · " + c.region : ""} · ${c.lower ? "lower" : "higher"} better · n=${c.n}`;
    const metaEl = sv("text", {x: left - 12, y: 38, "text-anchor": "end"}, clip(meta, 36));
    metaEl.append(sv("title", {}, meta)); svg.append(metaEl);
    svg.append(sv("line", {x1: x(c.min), x2: x(c.max), y1: 26, y2: 26, stroke: "var(--axis)", "stroke-width": 6, "stroke-linecap": "round"}));
    if (c.n > 1) svg.append(sv("line", {x1: x(c.median), x2: x(c.median), y1: 16, y2: 36, stroke: "var(--ink2)", "stroke-width": 2}));
    for (const d of c.dots) { const dot = sv("circle", {cx: x(d.value), cy: 26, r: 5, fill: "var(--s1)", stroke: "var(--surface)", "stroke-width": 2});
      svg.append(dot); const hit = sv("circle", {class: "hit", cx: x(d.value), cy: 26, r: 12});
      hover(hit, [[`${fmt(d.value)} ${c.unit}`, d.subject + (d.variant ? " · " + d.variant : ""), "var(--s1)"]]); svg.append(hit); }
    if (c.ours != null) { const s = 7, cx = x(c.ours);
      svg.append(sv("path", {d: `M${cx},${26 - s} L${cx + s},26 L${cx},${26 + s} L${cx - s},26 Z`, fill: "var(--ink)", stroke: "var(--surface)", "stroke-width": 2}));
      svg.append(sv("text", {class: "lbl", x: cx, y: 50, "text-anchor": "middle"}, `ours ${fmt(c.ours)} · rank ${c.rank} of ${c.size}`));
      const hit = sv("circle", {class: "hit", cx, cy: 26, r: 12}); hover(hit, [[`${fmt(c.ours)} ${c.unit}`, `ours · rank ${c.rank} of ${c.size}`, "var(--ink)"]]); svg.append(hit); }
    if (c.n > 1) svg.append(sv("text", {x: x(c.median), y: 12, "text-anchor": "middle"}, `median ${fmt(c.median)}`));
    if (c.n <= 3) c.dots.forEach((d, i) => svg.append(sv("text", {class: "lbl", x: x(d.value) + 10, y: 30 - (c.dots.length - 1 - i) * 13,
      "text-anchor": x(d.value) > W - 260 ? "end" : "start", dx: x(d.value) > W - 260 ? -20 : 0},
      `${d.subject} · ${fmt(d.value)} ${c.unit}${d.variant ? " (" + d.variant + ")" : ""}`)));
    host.append(svg); }
  $("compTable").replaceChildren(table([{label: "Feature", get: g => g.p.label}, {label: "Unit · condition", get: g => `${g.c.unit} ${g.c.condition}`},
    {label: "n", num: 1, get: g => g.c.n}, {label: "Min", num: 1, get: g => fmt(g.c.min)}, {label: "Median", num: 1, get: g => fmt(g.c.median)},
    {label: "Max", num: 1, get: g => fmt(g.c.max)}, {label: "Ours", num: 1, get: g => g.c.ours == null ? "–" : fmt(g.c.ours)},
    {label: "Competitors", get: g => g.c.dots.map(d => `${d.subject}${d.variant ? " (" + d.variant + ")" : ""} ${fmt(d.value)}`).join("; ")}], groups)); }

// tables
$("cands").append(D.candidates.length ? table([{label: "Id", get: c => c.id}, {label: "Candidate", get: c => c.title},
  {label: "Assessment → intent", get: c => `${c.assessment_label} → ${c.intent} (baseline ${c.baseline})`}, {label: "Target", get: c => c.target},
  {label: "Statement", get: c => c.statement}, {label: "Status", get: c => `${c.status} · priority ${c.priority}`},
  {label: "Open points", get: c => c.open.join("; ")}], D.candidates)
  : el("p", {class: "small"}, "No candidates: no feature was judged as Underperformance, Gap, Must-have or Strength."));
const judged = D.packages.map(p => ({p, j: D.assessments[p.attribute] || {}})).filter(r => r.j.assessment && r.j.assessment !== "not_assessed");
$("judgTable").append(judged.length ? table([{label: "Feature", get: r => r.p.label}, {label: "Assessment", get: r => r.j.assessment_label},
  {label: "Widespread", get: r => r.j.widespread}, {label: "Certainty", get: r => r.j.certainty}, {label: "Guard", get: r => r.j.guard},
  {label: "What exactly", get: r => r.j.what}], judged) : el("p", {class: "small"}, "No judged features in this run."));
$("trends").append(D.trends.length ? table([{label: "Feature", get: t => t.attribute}, {label: "Horizon", get: t => t.horizon || "–"},
  {label: "Direction", get: t => t.direction || "–"}, {label: "Sources", num: 1, get: t => t.sources ?? "–"}, {label: "Trend", get: t => t.claim}], D.trends)
  : el("p", {class: "small"}, "No trends in this run (see agent availability above)."));
$("foot").textContent = "Contains BMW-derived data. Generated locally from the saved analysis; keep it out of shared or public locations.";

drawDots(); drawComp();
const first = featureRows()[0] || D.packages[0]; if (first) select(first.attribute);
</script></body></html>
"""


def render(analysis: SituationAnalysis) -> str:
    payload = json.dumps(build_data(analysis), ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.replace("__DATA__", payload)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("analysis", type=Path, help="saved SituationAnalysis JSON")
    parser.add_argument(
        "--out", type=Path, help="output HTML (default: data/processed/reports/<run_id>.html)"
    )
    args = parser.parse_args()
    analysis = SituationAnalysis.model_validate_json(args.analysis.read_text())
    out = args.out or args.analysis.parent.parent / "reports" / f"{analysis.run_id}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(analysis), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
