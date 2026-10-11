import "server-only";
import { sql, type SQL } from "drizzle-orm";
import { cacheLife } from "next/cache";
import { db } from "@/server/db/client";

/** Which slice of feedback a view covers. `null` means "all". */
export type Scope = { derivate: string | null; country: string | null; engine: string | null };

export type Car = {
  derivate: string;
  name: string | null;
  engines: string[];
  feedback: number;
  net: number | null;
};

export type CategoryRow = {
  category: string;
  /** Feedback with at least one aspect in this category. */
  mentions: number;
  negative: number;
  positive: number;
  /** Feedback with a Feature Request aspect in this category. */
  demand: number;
  /** Mean |sentiment_score| of the negative aspects, 0–1. */
  severity: number;
  net: number | null;
  topIssue: string | null;
  /** negative / scope feedback. */
  reach: number;
  /** reach × severity. A transparent heuristic, not a model output. */
  priority: number;
};

export type Ranking = { total: number; rows: CategoryRow[]; unclassified: number };

export type Evidence = {
  id: string;
  derivate: string | null;
  country: string | null;
  engine: string | null;
  source: string | null;
  text: string;
  quote: string | null;
  term: string | null;
  issue: string;
  score: number;
};

const UNCLASSIFIED = "Unclassified";

export async function rows<T>(query: SQL): Promise<T[]> {
  return (await db.execute(query)).rows as T[];
}

export const inScope = (
  s: Scope,
) => sql`(${s.derivate}::text is null or e.derivate_code = ${s.derivate})
  and (${s.country}::text is null or e.country = ${s.country})
  and (${s.engine}::text is null or e.engine_type = ${s.engine})`;

export async function listCars(): Promise<Car[]> {
  "use cache";
  cacheLife("hours");
  return rows<Car>(sql`
    select e.derivate_code as derivate,
      max(e.sales_description) as name,
      coalesce(array_agg(distinct e.engine_type) filter (where e.engine_type is not null), '{}') as engines,
      count(distinct e.id)::int as feedback,
      avg(a.sentiment_score)::float8 as net
    from feedback_entries e
    left join feedback_aspects a on a.feedback_entry_id = e.id
    where e.derivate_code is not null
    group by 1 order by 1`);
}

export async function getScopeOptions(derivate: string) {
  "use cache";
  cacheLife("hours");
  const r = await rows<{ kind: "country" | "engine"; value: string; n: number }>(sql`
    select 'country' as kind, country as value, count(*)::int as n
    from feedback_entries where derivate_code = ${derivate} and country is not null group by 2
    union all
    select 'engine', engine_type, count(*)::int
    from feedback_entries where derivate_code = ${derivate} and engine_type is not null group by 2
    order by 3 desc`);
  return {
    countries: r.filter((o) => o.kind === "country"),
    engines: r.filter((o) => o.kind === "engine"),
  };
}

export async function getSummary(s: Scope) {
  "use cache";
  cacheLife("hours");
  const [r] = await rows<{ feedback: number; negative: number; net: number | null }>(sql`
    with s as (select e.id from feedback_entries e where ${inScope(s)}),
    asp as (select a.* from feedback_aspects a join s on s.id = a.feedback_entry_id)
    select (select count(*) from s)::int as feedback,
      (select count(distinct feedback_entry_id) from asp where sentiment = 'Negative')::int as negative,
      (select avg(sentiment_score) from asp)::float8 as net`);
  return r;
}

export async function getRanking(s: Scope): Promise<Ranking> {
  "use cache";
  cacheLife("hours");
  const r = await rows<Omit<CategoryRow, "reach" | "priority"> & { total: number }>(sql`
    with s as (select e.id from feedback_entries e where ${inScope(s)}),
    asp as (select a.* from feedback_aspects a join s on s.id = a.feedback_entry_id)
    select a.vfc_category as category,
      (select count(*) from s)::int as total,
      count(distinct a.feedback_entry_id)::int as mentions,
      count(distinct a.feedback_entry_id) filter (where a.sentiment = 'Negative')::int as negative,
      count(distinct a.feedback_entry_id) filter (where a.sentiment = 'Positive')::int as positive,
      count(distinct a.feedback_entry_id) filter (where a.issue_type = 'Feature Request')::int as demand,
      coalesce(avg(abs(a.sentiment_score)) filter (where a.sentiment = 'Negative'), 0)::float8 as severity,
      avg(a.sentiment_score)::float8 as net,
      mode() within group (order by a.issue_type) filter (where a.sentiment = 'Negative') as "topIssue"
    from asp a group by 1`);
  const total = r[0]?.total ?? (await getSummary(s)).feedback;
  const scored = r.map((row) => {
    const reach = total ? row.negative / total : 0;
    return { ...row, reach, priority: reach * row.severity };
  });
  return {
    total,
    rows: scored
      .filter((x) => x.category !== UNCLASSIFIED)
      .sort((a, b) => b.priority - a.priority || b.negative - a.negative),
    unclassified: scored.find((x) => x.category === UNCLASSIFIED)?.mentions ?? 0,
  };
}

export async function getCategoryDetail(s: Scope, category: string) {
  "use cache";
  cacheLife("hours");
  const base = sql`from feedback_aspects a join feedback_entries e on e.id = a.feedback_entry_id
    where ${inScope(s)} and a.vfc_category = ${category}`;
  const [issues, terms] = await Promise.all([
    rows<{ issue: string; sentiment: string; n: number }>(sql`
      select a.issue_type as issue, a.sentiment, count(distinct a.feedback_entry_id)::int as n
      ${base} group by 1, 2 order by 3 desc`),
    rows<{ term: string; negative: number; positive: number; demand: number; total: number }>(sql`
      select coalesce(a.aspect_term, '(no term)') as term,
        count(distinct a.feedback_entry_id) filter (where a.sentiment = 'Negative')::int as negative,
        count(distinct a.feedback_entry_id) filter (where a.sentiment = 'Positive')::int as positive,
        count(distinct a.feedback_entry_id) filter (where a.issue_type = 'Feature Request')::int as demand,
        count(distinct a.feedback_entry_id)::int as total
      ${base} group by 1 order by 2 desc, 5 desc limit 10`),
  ]);
  return { issues, terms };
}

/** Verbatims for one category and sentiment, one per feedback, strongest first. */
export async function getEvidence(
  s: Scope,
  category: string,
  sentiment: "Negative" | "Positive",
  limit: number,
) {
  "use cache";
  cacheLife("hours");
  return rows<Evidence>(sql`
    select * from (
      select distinct on (e.id) e.feedback_explorer_id as id, e.derivate_code as derivate,
        e.country, e.engine_type as engine,
        e.source, e.raw_feedback as text, a.quote_snippet as quote, a.aspect_term as term,
        a.issue_type as issue, abs(a.sentiment_score)::float8 as score
      from feedback_aspects a join feedback_entries e on e.id = a.feedback_entry_id
      where ${inScope(s)} and a.vfc_category = ${category} and a.sentiment = ${sentiment}
      order by e.id, abs(a.sentiment_score) desc
    ) x order by score desc, id limit ${limit}`);
}

/** Sales volume per car and sales market (EU, US, CN, RoW). 2030 is a forecast. No engine split. */
export type Sale = { model: string; market: string; v2024: number; v2025: number; v2030: number };

export async function getSales(): Promise<Sale[]> {
  "use cache";
  cacheLife("hours");
  return rows<Sale>(sql`
    select model_code as model, market_code as market,
      volume_2024 as v2024, volume_2025 as v2025, volume_2030 as v2030
    from sales order by 1, 2`);
}
