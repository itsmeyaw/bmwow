import "server-only";
import { sql } from "drizzle-orm";
import { cacheLife } from "next/cache";
import { rows } from "@/server/analysis/queries";

/**
 * Reads of the stored situation-analysis runs (tables analysis_*, written by
 * python/scripts/export_analysis.py). One run = one car in one region.
 */

export type RunSummary = {
  runId: string;
  modelCode: string;
  modelName: string | null;
  segment: string | null;
  region: string;
  createdAt: string;
  llmModel: string | null;
  requirements: number;
  features: number;
  topRequirement: string | null;
};

export type AgentStatus = Record<
  "baseline" | "competition" | "feedback" | "trends",
  { status: string; unavailable: string[]; errors: string[] }
>;

export type Run = RunSummary & { agentStatus: AgentStatus; notes: string[] };

export type FeatureRow = {
  attribute: string;
  label: string;
  area: string;
  rank: number;
  assessment: string;
  method: string;
  certainty: string | null;
  whatExactly: string | null;
  isMapped: boolean;
  reqId: string | null;
  requirement: string | null;
  changeIntent: string | null;
  targetOperator: string | null;
  targetValue: number | null;
  targetUnit: string | null;
  targetCondition: string | null;
  problemShare: number | null;
  competitorComparisons: number;
};

export type Requirement = {
  reqId: string;
  title: string;
  statement: string;
  customerValue: string | null;
  subTheme: string | null;
  assessment: string;
  changeIntent: string;
  baselineStatus: string;
  baselineRationale: string | null;
  targetOperator: string | null;
  targetValue: number | null;
  targetUnit: string | null;
  targetCondition: string | null;
  targetRule: string | null;
  options: { label: string; value: number; unit: string; condition: string }[];
  acceptance: {
    description: string;
    verification_method: string;
    test_conditions: string[];
  } | null;
  customerFacts: string[];
  openPoints: string[];
  wording: string;
};

export type Finding = {
  findingId: string;
  agent: string;
  subject: string;
  claim: string;
  direction: string | null;
  region: string | null;
  value: number | null;
  unit: string | null;
  qualifier: string | null;
};

export type CompetitorValue = {
  unit: string;
  condition: string;
  region: string | null;
  n: number;
  minimum: number;
  median: number;
  maximum: number;
  lowerIsBetter: boolean;
  ours: number | null;
  oursRank: number | null;
  fieldSize: number | null;
  oursVsMedian: number | null;
  findingIds: string[];
};

export type Signal = {
  findingId: string;
  direction: string;
  region: string | null;
  share: number;
  k: number;
  n: number;
  ciLow: number;
  ciHigh: number;
  thin: boolean;
  differsFrom: string | null;
};

export type Quote = { sourceId: string; direction: string | null; text: string };
export type SubTheme = { direction: string; name: string; k: number; ofTotal: number };
export type Trend = { findingId: string; claim: string; horizon: string | null; thin: boolean };
export type Source = {
  sourceId: string;
  kind: string;
  sourceType: string | null;
  title: string | null;
  url: string | null;
  excerpt: string;
};

export type FeatureDetail = {
  feature: FeatureRow & {
    widespread: string | null;
    reasoning: string | null;
    ruleSuggestion: string | null;
    guardStatus: string | null;
    facts: string[];
    coverage: string[];
  };
  requirement: Requirement | null;
  ours: Finding[];
  competitorFacts: Finding[];
  competitorValues: CompetitorValue[];
  signals: Signal[];
  subThemes: SubTheme[];
  quotes: Quote[];
  trends: Trend[];
  sources: Source[];
};

/** "US", "EU", "CN" for a one-region run; "ALL" for a run over all regions the car is sold in. */
export const ALL = "ALL";
const REGION_KEY = sql`(case when cardinality(r.regions) = 1 then r.regions[1] else 'ALL' end)`;

const RUN_COLUMNS = sql`
  r.run_id as "runId", r.model_code as "modelCode", r.model_name as "modelName",
  r.segment, ${REGION_KEY} as region, r.created_at::text as "createdAt", r.llm_model as "llmModel",
  (select count(*) from analysis_requirements q where q.run_id = r.run_id)::int as requirements,
  (select count(*) from analysis_features f where f.run_id = r.run_id)::int as features,
  (select q.statement from analysis_requirements q where q.run_id = r.run_id
     order by length(q.req_id), q.req_id limit 1) as "topRequirement"`;

/** One run per car and region (the latest export); "ALL" first, then the single regions. */
export async function listRuns(): Promise<RunSummary[]> {
  "use cache";
  cacheLife("minutes");
  return rows<RunSummary>(sql`
    select * from (
      select distinct on (r.model_code, ${REGION_KEY}) ${RUN_COLUMNS}
      from analysis_runs r
      order by r.model_code, ${REGION_KEY}, r.created_at desc
    ) runs
    order by "modelCode", region <> 'ALL', region`);
}

export async function getRun(modelCode: string, region: string): Promise<Run | null> {
  "use cache";
  cacheLife("minutes");
  const [run] = await rows<Run>(sql`
    select ${RUN_COLUMNS}, r.agent_status as "agentStatus", r.notes
    from analysis_runs r
    where r.model_code = ${modelCode}
      and (case when ${region} = 'ALL' then cardinality(r.regions) > 1
                else r.regions = array[${region}]::text[] end)
    order by r.created_at desc limit 1`);
  return run ?? null;
}

export async function listFeatures(runId: string): Promise<FeatureRow[]> {
  "use cache";
  cacheLife("minutes");
  return rows<FeatureRow>(sql`
    select o.attribute, o.label, o.area, o.rank, o.assessment, o.method, o.certainty,
      o.what_exactly as "whatExactly", f.is_mapped as "isMapped", o.req_id as "reqId",
      o.requirement, o.change_intent as "changeIntent", o.target_operator as "targetOperator",
      o.target_value as "targetValue", o.target_unit as "targetUnit",
      o.target_condition as "targetCondition", o.problem_share as "problemShare",
      o.n_competitor_comparisons::int as "competitorComparisons"
    from analysis_feature_overview o
    join analysis_features f on f.run_id = o.run_id and f.attribute = o.attribute
    where o.run_id = ${runId}
    order by o.rank`);
}

export async function getFeatureDetail(
  runId: string,
  attribute: string,
): Promise<FeatureDetail | null> {
  "use cache";
  cacheLife("minutes");
  const [feature] = await rows<FeatureDetail["feature"]>(sql`
    select o.attribute, o.label, o.area, o.rank, o.assessment, o.method, o.certainty,
      o.what_exactly as "whatExactly", f.is_mapped as "isMapped", o.req_id as "reqId",
      o.requirement, o.change_intent as "changeIntent", o.target_operator as "targetOperator",
      o.target_value as "targetValue", o.target_unit as "targetUnit",
      o.target_condition as "targetCondition", o.problem_share as "problemShare",
      o.n_competitor_comparisons::int as "competitorComparisons",
      f.widespread, f.reasoning, f.rule_suggestion as "ruleSuggestion",
      f.guard_status as "guardStatus", f.facts, f.coverage
    from analysis_feature_overview o
    join analysis_features f on f.run_id = o.run_id and f.attribute = o.attribute
    where o.run_id = ${runId} and o.attribute = ${attribute}`);
  if (!feature) return null;
  const at = sql`run_id = ${runId} and attribute = ${attribute}`;
  const [requirements, findings, competitorValues, signals, subThemes, quotes, trends] =
    await Promise.all([
      rows<Requirement>(sql`
        select req_id as "reqId", title, statement, customer_value as "customerValue",
          sub_theme as "subTheme", assessment, change_intent as "changeIntent",
          baseline_status as "baselineStatus", baseline_rationale as "baselineRationale",
          target_operator as "targetOperator", target_value as "targetValue",
          target_unit as "targetUnit", target_condition as "targetCondition",
          target_rule as "targetRule", options, acceptance, customer_facts as "customerFacts",
          open_points as "openPoints", wording
        from analysis_requirements where ${at}`),
      rows<Finding>(sql`
        select finding_id as "findingId", agent, subject, claim, direction, region, value, unit,
          qualifier
        from analysis_findings
        where ${at} and agent in ('baseline', 'competition')
        order by agent, value is null, finding_id`),
      rows<CompetitorValue>(sql`
        select unit, condition, region, n, minimum, median, maximum,
          lower_is_better as "lowerIsBetter", ours, ours_rank as "oursRank",
          field_size as "fieldSize", ours_vs_median as "oursVsMedian", finding_ids as "findingIds"
        from analysis_competitor_values where ${at}
        order by ours is null, n desc, ordinal`),
      rows<Signal>(sql`
        select finding_id as "findingId", direction, region, share, k, n, ci_low as "ciLow",
          ci_high as "ciHigh", thin, differs_from as "differsFrom"
        from analysis_customer_signals where ${at}
        order by array_position(array['problem','request','strength','neutral'], direction),
          region nulls first`),
      rows<SubTheme>(sql`
        select direction, name, k, of_total as "ofTotal"
        from analysis_sub_themes where ${at} order by direction, k desc limit 12`),
      rows<Quote>(sql`
        select source_id as "sourceId", direction, text
        from analysis_quotes where ${at} order by ordinal`),
      rows<Trend>(sql`
        select finding_id as "findingId", claim, horizon, thin
        from analysis_trends where ${at}`),
    ]);
  const cited = [
    ...findings.map((f) => f.findingId),
    ...competitorValues.flatMap((v) => v.findingIds),
    ...trends.map((t) => t.findingId),
  ];
  const sources = cited.length
    ? await rows<Source>(sql`
        select distinct s.source_id as "sourceId", s.kind, s.source_type as "sourceType", s.title,
          s.url, s.excerpt
        from analysis_finding_sources fs
        join analysis_sources s on s.run_id = fs.run_id and s.source_id = fs.source_id
        where fs.run_id = ${runId}
          and fs.finding_id in (${sql.join(
            [...new Set(cited)].map((id) => sql`${id}`),
            sql`, `,
          )})
          and s.kind <> 'feedback'
        limit 40`)
    : [];
  return {
    feature,
    requirement: requirements[0] ?? null,
    ours: findings.filter((f) => f.agent === "baseline"),
    competitorFacts: findings.filter((f) => f.agent === "competition"),
    competitorValues,
    signals,
    subThemes,
    quotes,
    trends,
    sources,
  };
}
