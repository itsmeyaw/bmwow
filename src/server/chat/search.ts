import "server-only";
import { openai } from "@ai-sdk/openai";
import { embed } from "ai";
import { sql } from "drizzle-orm";
import { inScope, rows, type Scope } from "@/server/analysis/queries";
import { rrf } from "@/server/chat/lib";

/** Must match scripts/preprocess.ts, or query and stored vectors are not comparable. */
const EMBED_MODEL = "text-embedding-3-large";
const DIMENSIONS = 1536;

export type Hit = {
  id: string;
  derivate: string | null;
  country: string | null;
  engine: string | null;
  source: string | null;
  text: string;
  /** Strongest quote in the requested category (or overall). */
  quote: string | null;
  aspects: { category: string; sentiment: string; issue: string; term: string | null }[];
};

export type SearchFilter = {
  category: string | null;
  sentiment: "Negative" | "Positive" | null;
  limit: number;
};

/** Hybrid search: semantic (pgvector cosine) + lexical (search_tsv), fused with RRF. */
export async function searchFeedback(query: string, scope: Scope, f: SearchFilter): Promise<Hit[]> {
  const { embedding } = await embed({
    model: openai.embedding(EMBED_MODEL),
    value: query,
    dimensions: DIMENSIONS,
  });
  const where = sql`${inScope(scope)} and (${f.category}::text is null or exists (
    select 1 from feedback_aspects a where a.feedback_entry_id = e.id
      and a.vfc_category = ${f.category}
      and (${f.sentiment}::text is null or a.sentiment = ${f.sentiment})))`;
  const [semantic, lexical] = await Promise.all([
    // ponytail: exact scan over the filtered set (~10k rows). HNSW drops rows under
    // selective filters; switch to it with hnsw.iterative_scan once the table grows.
    rows<{ id: string }>(sql`
      with s as materialized (select e.id, e.embedding from feedback_entries e where ${where})
      select id from s order by embedding <=> ${JSON.stringify(embedding)}::vector limit 40`),
    rows<{ id: string }>(sql`
      select e.id from feedback_entries e, websearch_to_tsquery('english', ${query}) q
      where ${where} and e.search_tsv @@ q
      order by ts_rank_cd(e.search_tsv, q) desc limit 40`),
  ]);
  const ids = rrf([semantic.map((r) => r.id), lexical.map((r) => r.id)]).slice(0, f.limit);
  if (!ids.length) return [];

  const hits = await rows<Hit & { uuid: string }>(sql`
    select e.id as uuid, e.feedback_explorer_id as id, e.derivate_code as derivate, e.country,
      e.engine_type as engine, e.source, e.raw_feedback as text,
      (array_agg(a.quote_snippet order by abs(a.sentiment_score) desc nulls last)
        filter (where a.quote_snippet is not null
          and (${f.category}::text is null or a.vfc_category = ${f.category})))[1] as quote,
      coalesce(json_agg(json_build_object('category', a.vfc_category, 'sentiment', a.sentiment,
        'issue', a.issue_type, 'term', a.aspect_term)) filter (where a.id is not null), '[]') as aspects
    from feedback_entries e left join feedback_aspects a on a.feedback_entry_id = e.id
    where e.id = any(${`{${ids.join(",")}}`}::uuid[])
    group by e.id`);
  const byId = new Map(hits.map(({ uuid, ...h }) => [uuid, h]));
  return ids.map((id) => byId.get(id)!).filter(Boolean);
}
