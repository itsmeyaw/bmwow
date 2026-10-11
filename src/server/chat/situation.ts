import "server-only";
import { tool } from "ai";
import { z } from "zod";
import { assessmentLabel, assessmentSuggestion } from "@/lib/assessment";
import { categoryLabel, categoryOf } from "@/lib/feature-category";
import { pct } from "@/lib/format";
import {
  getFeatureDetail,
  getRun,
  listFeatures,
  listRuns,
  type FeatureDetail,
  type FeatureRow,
  type Run,
} from "@/server/situation/queries";
import { regionLabel, shortFeedbackId, type SituationPage } from "./situation-lib";

/**
 * The chat's view of the stored situation-analysis runs (tables analysis_*): what the
 * /situation pages show, as text for the model, plus tools to read any run or feature.
 */

export const SITUATION_INSTRUCTIONS = `## Situation analysis (requirement recommendations)
- A run analyses one car in one region (EU, US, CN) or in all its regions ("All"): our current model (price list, studies, sales), competitors (like-for-like values: same unit, test standard and powertrain), customer feedback shares, and trends.
- Each feature gets an assessment: Underperformance (stored ID gap: a comparable benchmark shows we trail competitors), Gap (stored ID demand: an unmet customer need, supported by problems, requests or market trends), Must-have (stored ID hygiene_factor: customers complain but competitors are no better; keep the level, fix the complaints), Strength (we lead or customers praise it), Unclear (too little evidence). Always use the displayed names in answers; never call the assessment "Demand" or "hygiene_factor". Customer-only complaints support Gap; Underperformance requires a comparable benchmark that shows our vehicle trails. Older runs may use gap for customer-only complaints: explain the supporting evidence and do not claim a competitive shortfall without a benchmark.
- method "judge" = judged by an LLM with a fixed rubric and checked by code rules; "rule" = computed by code from the numbers only (low certainty).
- Features are grouped into categories: Exterior, Interior, Powertrain, Driver assistance, Digital & UX, Ownership & business.
- Requirements (REQ-n) are the recommended features, in order of customer impact. A target comes from the competitor median, best in class or today's value; "set by PM" means no comparable number.
- On a situation page, answer only from that car and region (getSituationRun / getSituationFeature with the page's values). Use another car or region only when the user names it, and say that you switched. On the overview, compare all runs.
- Cite requirements as [REQ-n] and customer feedback as [G60-0042]-style ids from the tool output. Quote numbers exactly as the tools give them; never compute new shares or targets.
- If a run has no customer feedback for its region, say so instead of guessing.`;

const target = (r: {
  targetOperator: string | null;
  targetValue: number | null;
  targetUnit: string | null;
  targetCondition: string | null;
}) =>
  r.targetValue == null
    ? "set by PM"
    : `${r.targetOperator} ${r.targetValue} ${r.targetUnit ?? ""}${r.targetCondition ? ` (${r.targetCondition})` : ""}`;

function runHeader(run: Run) {
  const status = Object.entries(run.agentStatus ?? {})
    .map(
      ([agent, s]) =>
        `${agent}: ${s.status}${s.unavailable.length ? ` (${s.unavailable.join("; ")})` : ""}`,
    )
    .join(" | ");
  return `Run ${run.runId}: ${run.modelCode} (${run.modelName ?? "?"}), ${regionLabel(run.region)}, segment ${run.segment ?? "?"}, created ${run.createdAt}.
Evidence views: ${status}`;
}

function featureTable(features: FeatureRow[]) {
  const req = features.filter((f) => f.reqId);
  const other = features.filter(
    (f) => !f.reqId && f.assessment !== "unclear" && f.assessment !== "not_assessed",
  );
  const unclear = features.length - req.length - other.length;
  const reqRows = req.map(
    (f) =>
      `| ${f.reqId} | ${f.label} (${f.attribute}) | ${categoryLabel(categoryOf(f.attribute, f.area))} | ${assessmentLabel(f.assessment)} (${f.method}) | ${target(f)} | ${f.problemShare == null ? "–" : pct(f.problemShare)} | ${f.requirement ?? ""} |`,
  );
  const otherRows = other.map(
    (f) =>
      `- ${f.label} (${f.attribute}), ${categoryLabel(categoryOf(f.attribute, f.area))}: ${assessmentLabel(f.assessment)} (${f.method}), problem share ${f.problemShare == null ? "–" : pct(f.problemShare)}, ${f.competitorComparisons} competitor comparisons`,
  );
  return `### Recommended requirements
| REQ | Feature | Category | Assessment | Target | Problem share | Requirement |
|---|---|---|---|---|---|---|
${reqRows.join("\n") || "| – | none | | | | | |"}

### Other assessed features (not recommended)
${otherRows.join("\n") || "- none"}
${unclear} further features had too little evidence to decide.`;
}

function featureText(d: FeatureDetail) {
  const f = d.feature;
  const r = d.requirement;
  const lines = [
    `## ${f.label} (${f.attribute}) — ${assessmentLabel(f.assessment)} (${f.method}, certainty ${f.certainty ?? "–"}, rank #${f.rank})`,
    f.whatExactly && `What exactly: ${f.whatExactly}`,
    f.reasoning && `Reasoning: ${f.reasoning}`,
    f.ruleSuggestion &&
      `Code's rule-based suggestion: ${assessmentSuggestion(f.ruleSuggestion)}; code checks: ${f.guardStatus ?? "–"}`,
    f.facts.length && `Computed facts:\n${f.facts.map((x) => `- ${x}`).join("\n")}`,
    r &&
      `Requirement ${r.reqId}: ${r.statement}\nTarget: ${target(r)}; why: ${r.targetRule ?? "–"}; current model: ${r.baselineStatus} (${r.baselineRationale ?? ""})${
        r.options.length
          ? `\nTarget options: ${r.options.map((o) => `${o.label} ${o.value} ${o.unit}`).join(", ")}`
          : ""
      }${r.openPoints.length ? `\nOpen points: ${r.openPoints.join("; ")}` : ""}`,
    d.signals.length &&
      `Customer shares:\n${d.signals
        .map(
          (s) =>
            `- ${s.direction}, ${s.region ?? "all regions"}: ${pct(s.share)} (${s.k} of ${s.n}, 95% CI ${pct(s.ciLow)}–${pct(s.ciHigh)})${s.thin ? ", thin sample" : ""}`,
        )
        .join("\n")}`,
    d.subThemes.length &&
      `What customers mean: ${d.subThemes.map((t) => `${t.direction} "${t.name}" ${t.k} of ${t.ofTotal}`).join("; ")}`,
    d.quotes.length &&
      `Customer feedback (verbatim):\n${d.quotes.map((q) => `- [${shortFeedbackId(q.sourceId)}] (${q.direction ?? "–"}) ${q.text}`).join("\n")}`,
    d.competitorValues.length &&
      `Competitor comparison (one value per competitor):\n${d.competitorValues
        .map(
          (v) =>
            `- ${v.unit}, ${v.condition || "–"}: n=${v.n}, min ${v.minimum}, median ${v.median}, max ${v.maximum}${v.lowerIsBetter ? " (lower is better)" : ""}; ours ${v.ours ?? "–"}${v.oursRank ? ` (rank ${v.oursRank} of ${v.fieldSize})` : ""}`,
        )
        .join("\n")}`,
    d.competitorFacts.length &&
      `Competitor findings:\n${d.competitorFacts
        .slice(0, 8)
        .map((x) => `- [${x.findingId}] ${x.claim}`)
        .join("\n")}`,
    d.ours.length &&
      `Our current model:\n${d.ours
        .slice(0, 8)
        .map((x) => `- [${x.findingId}] ${x.claim}`)
        .join("\n")}`,
    d.trends.length &&
      `Trends:\n${d.trends.map((t) => `- [${t.findingId}] ${t.claim}`).join("\n")}`,
    f.coverage.length && `Missing evidence: ${f.coverage.join("; ")}`,
    d.sources.length &&
      `Sources: ${d.sources
        .slice(0, 10)
        .map((s) => (s.url ? `[${s.title || s.url}](${s.url})` : (s.title ?? s.sourceId)))
        .join("; ")}`,
  ];
  return lines.filter(Boolean).join("\n\n");
}

async function overview() {
  const runs = await listRuns();
  if (!runs.length) return "No situation-analysis runs are stored yet.";
  return runs
    .map(
      (r) =>
        `- ${r.modelCode} (${r.modelName ?? "?"}), ${regionLabel(r.region)}: ${r.requirements} requirements of ${r.features} features; #1: ${r.topRequirement ?? "none"}`,
    )
    .join("\n");
}

/** Resolves a page's car and region to its stored run ("ALL" if the car has it, else its first). */
async function resolveRun(derivate: string, region: string | null) {
  const runs = (await listRuns()).filter((r) => r.modelCode === derivate);
  if (!runs.length) return null;
  return getRun(derivate, region ?? runs[0].region);
}

/** The situation page the user is on, as text for the system prompt. */
export async function situationContext(page: SituationPage): Promise<string> {
  if (!page.derivate) {
    return `# Current page: situation analysis overview (all cars and regions)
## Stored runs
${await overview()}`;
  }
  const run = await resolveRun(page.derivate, page.region);
  if (!run) {
    return `# Current page: situation analysis of ${page.derivate}\nNo stored run for ${page.derivate} in ${regionLabel(page.region)}.`;
  }
  const features = await listFeatures(run.runId);
  const open = page.feature ? await getFeatureDetail(run.runId, page.feature) : null;
  return `# Current page: situation analysis of ${run.modelCode}, ${regionLabel(run.region)}
${runHeader(run)}

${featureTable(features)}
${open ? `\n# Feature open in the side panel\n${featureText(open)}` : ""}

## Other stored runs
${await overview()}`;
}

const regionInput = z
  .enum(["ALL", "EU", "US", "CN"])
  .nullable()
  .describe("ALL = run over all regions of the car; null = the car's default run.");

export const situationTools = {
  getSituationRun: tool({
    description:
      "A stored situation-analysis run of one car in one region: recommended requirements (REQ-n) with targets, and the other assessed features.",
    inputSchema: z.object({
      derivate: z.string().describe("Car code, e.g. G60."),
      region: regionInput,
    }),
    execute: async ({ derivate, region }) => {
      const run = await resolveRun(derivate.toUpperCase(), region);
      if (!run) return `No stored run for ${derivate} in ${regionLabel(region)}.`;
      return `${runHeader(run)}\n\n${featureTable(await listFeatures(run.runId))}`;
    },
  }),
  getSituationFeature: tool({
    description:
      "The full analysis of one feature in a run: reasoning with cited ids, requirement and target options, customer shares, sub-themes, verbatim feedback, competitor comparison, our model, trends and sources.",
    inputSchema: z.object({
      derivate: z.string().describe("Car code, e.g. G60."),
      region: regionInput,
      attribute: z
        .string()
        .describe("Feature key from the run table, e.g. fast_charging or unmapped:seats_comfort."),
    }),
    execute: async ({ derivate, region, attribute }) => {
      const run = await resolveRun(derivate.toUpperCase(), region);
      if (!run) return `No stored run for ${derivate} in ${regionLabel(region)}.`;
      const d = await getFeatureDetail(run.runId, attribute);
      return d
        ? `${run.modelCode}, ${regionLabel(run.region)}\n${featureText(d)}`
        : `Feature ${attribute} is not in run ${run.runId}.`;
    },
  }),
};
