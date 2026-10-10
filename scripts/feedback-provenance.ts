import { createHash } from "node:crypto";
import type { PoolClient } from "pg";

export type Origin = {
  source_file: string;
  source_hash: string;
  locator: Record<string, unknown>;
};
export type Processing = {
  preprocessing: string;
  enrichment_model: string;
  prompt_version: string;
  taxonomy_hash: string;
  embedding_model: string;
  embedding_dimensions: number;
};
export type FeedbackProvenance = {
  schema_version: 1;
  revision_id: string;
  input_hash: string;
  text_hash: string;
  processing_hash: string;
  processing: Processing;
  origins: Origin[];
  raw_classifications: Record<string, unknown>[];
  original_rows: Record<string, unknown>[];
};

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([k, v]) => [k, canonical(v)]),
    );
  return value;
}

export function hash(value: unknown): string {
  return (
    "sha256:" +
    createHash("sha256")
      .update(JSON.stringify(canonical(value)))
      .digest("hex")
  );
}

export function stableUuid(value: unknown): string {
  const digest = hash(value).slice(7, 39).split("");
  digest[12] = "5";
  digest[16] = "8";
  const raw = digest.join("");
  return `${raw.slice(0, 8)}-${raw.slice(8, 12)}-${raw.slice(12, 16)}-${raw.slice(16, 20)}-${raw.slice(20)}`;
}

export function provenance(
  identity: string,
  input: unknown,
  text: string,
  processing: Processing,
  origins: Origin[],
  classifications: Record<string, unknown>[],
): FeedbackProvenance {
  const inputHash = hash(input);
  const processingHash = hash(processing);
  return {
    schema_version: 1,
    revision_id: stableUuid([identity, inputHash, processingHash]),
    input_hash: inputHash,
    text_hash: hash(text),
    processing_hash: processingHash,
    processing,
    origins,
    raw_classifications: classifications,
    original_rows: Array.isArray(input) ? input : [],
  };
}

export function complete(existing: FeedbackProvenance | null, wanted: FeedbackProvenance): boolean {
  return (
    existing?.input_hash === wanted.input_hash &&
    existing?.processing_hash === wanted.processing_hash
  );
}

export function reusableEmbedding(
  existing: FeedbackProvenance | null,
  wanted: FeedbackProvenance,
): boolean {
  return (
    !!existing &&
    existing.text_hash === wanted.text_hash &&
    existing.processing.embedding_model === wanted.processing.embedding_model &&
    existing.processing.embedding_dimensions === wanted.processing.embedding_dimensions &&
    existing.processing.preprocessing === wanted.processing.preprocessing
  );
}

function snake(record: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(record).map(([k, v]) => [k.replace(/[A-Z]/g, (c) => "_" + c.toLowerCase()), v]),
  );
}

export async function storeRevision(
  client: PoolClient,
  entry: Record<string, unknown>,
  aspects: Record<string, unknown>[],
  version: FeedbackProvenance,
  embedding: number[] | null,
  expectedRevision: string | null,
): Promise<"written" | "skipped"> {
  await client.query("BEGIN");
  try {
    const identity = String(entry.feedbackExplorerId);
    await client.query("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", [identity]);
    const current = (
      await client.query(
        "SELECT id, revision_id, provenance FROM feedback_entries WHERE feedback_explorer_id = $1",
        [identity],
      )
    ).rows[0];
    if (complete(current?.provenance ?? null, version)) {
      await client.query("COMMIT");
      return "skipped";
    }
    if ((current?.revision_id ?? null) !== expectedRevision)
      throw new Error("Feedback changed during import; reload and retry the selection");
    const parentId = current?.id ?? stableUuid(["feedback", identity]);
    const createdAt = new Date().toISOString();
    const payload = {
      parent: {
        ...snake(entry),
        id: parentId,
        created_at: createdAt,
        provenance: version,
        revision_id: version.revision_id,
      },
      aspects: aspects.map((a, i) => ({
        ...snake(a),
        id: stableUuid([version.revision_id, i]),
        feedback_entry_id: parentId,
        created_at: createdAt,
      })),
    };
    await client.query(
      "INSERT INTO feedback_revisions (id, feedback_explorer_id, input_hash, processing_hash, payload, embedding) " +
        "VALUES ($1,$2,$3,$4,$5::jsonb,$6::vector) ON CONFLICT (id) DO NOTHING",
      [
        version.revision_id,
        identity,
        version.input_hash,
        version.processing_hash,
        JSON.stringify(payload),
        embedding ? JSON.stringify(embedding) : null,
      ],
    );
    // A replay of a historical version reuses its immutable original enrichment and timestamp.
    const stored = (
      await client.query("SELECT payload, embedding::text FROM feedback_revisions WHERE id = $1", [
        version.revision_id,
      ])
    ).rows[0];
    const parent = stored.payload.parent;
    await client.query(
      "INSERT INTO feedback_entries (id,feedback_explorer_id,source,brand,sales_description,country,derivate_code,engine_type,raw_feedback,embedding,created_at,revision_id,provenance) " +
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::vector,$11,$12,$13::jsonb) " +
        "ON CONFLICT (feedback_explorer_id) DO UPDATE SET source=excluded.source,brand=excluded.brand,sales_description=excluded.sales_description,country=excluded.country,derivate_code=excluded.derivate_code,engine_type=excluded.engine_type,raw_feedback=excluded.raw_feedback,embedding=excluded.embedding,created_at=excluded.created_at,revision_id=excluded.revision_id,provenance=excluded.provenance",
      [
        parentId,
        identity,
        parent.source,
        parent.brand,
        parent.sales_description,
        parent.country,
        parent.derivate_code,
        parent.engine_type,
        parent.raw_feedback,
        stored.embedding,
        parent.created_at,
        version.revision_id,
        JSON.stringify(version),
      ],
    );
    await client.query("DELETE FROM feedback_aspects WHERE feedback_entry_id = $1", [parentId]);
    for (const a of stored.payload.aspects)
      await client.query(
        "INSERT INTO feedback_aspects (id,feedback_entry_id,feedback_type,vfc_category,aspect_term,aspect_label_raw,issue_type,quote_snippet,sentiment,sentiment_score,extraction_source,created_at) " +
          "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)",
        [
          a.id,
          parentId,
          a.feedback_type,
          a.vfc_category,
          a.aspect_term,
          a.aspect_label_raw,
          a.issue_type,
          a.quote_snippet,
          a.sentiment,
          a.sentiment_score,
          a.extraction_source,
          a.created_at,
        ],
      );
    await client.query("COMMIT");
    return "written";
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  }
}
