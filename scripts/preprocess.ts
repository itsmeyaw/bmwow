import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { parseArgs, parseEnv } from "node:util";
import { parse } from "csv-parse/sync";
import OpenAI from "openai";
import { zodTextFormat } from "openai/helpers/zod";
import pg from "pg";
import { z } from "zod";
import { type NewFeedbackAspect, type NewFeedbackEntry } from "../src/server/db/schema";
import {
  complete,
  hash,
  provenance,
  reusableEmbedding,
  storeRevision,
  type FeedbackProvenance,
  type Origin,
} from "./feedback-provenance";

const VFC_CATEGORIES = [
  "Infotainment & Connectivity",
  "ADAS / Driving Assistance",
  "Powertrain & Performance",
  "Chassis, Ride & Handling",
  "Electrification & Charging",
  "Climate Control",
  "Seats & Comfort",
  "Interior Design & Materials",
  "Exterior Design & Body",
  "Storage & Luggage",
  "Access, Locking & Keys",
  "Visibility & Lighting",
  "Instruments & Controls",
  "Safety & Restraints",
  "Service, Docs & Support",
  "Unclassified",
] as const;
const ISSUE_TYPES = [
  "Praise",
  "Usability Difficulty",
  "Malfunction",
  "Damage & Leaks",
  "Performance Shortfall",
  "Feature Request",
  "Noise, Vibration & Odor",
  "Space & Storage Shortfall",
  "Value & Pricing",
  "Information Quality",
  "Unclassified",
] as const;

const MODEL = "gpt-6-luna";
const EMBED_MODEL = "text-embedding-3-large";
const TAXONOMY_PATH = "scripts/vfc-taxonomy.json";
const CSV_DIR = "data/feedbacks";
const PLACEHOLDERS = new Set(["n/a", "none", "na", "null", "-", "."]);

const TaxonomySchema = z.object({
  vfc_category: z.record(z.string(), z.enum(VFC_CATEGORIES)),
  issue_type: z.record(z.string(), z.enum(ISSUE_TYPES)),
});
const EnrichmentSchema = z.object({
  scores: z.array(z.number()),
  extracted: z.array(
    z.object({
      vfc_category: z.enum(VFC_CATEGORIES),
      issue_type: z.enum(ISSUE_TYPES),
      aspect_term: z.string(),
      quote_snippet: z.string(),
      intensity: z.number(),
    }),
  ),
});
type Taxonomy = z.infer<typeof TaxonomySchema>;
type Enrichment = z.infer<typeof EnrichmentSchema>;
type Row = Record<string, string | undefined>;
type Feedback = ReturnType<typeof groupFeedbacks>[number];
type Aspect = Feedback["aspects"][number];

const clean = (v: string | undefined) => v?.trim() || null;
const norm = (v: string | undefined) => v?.replace(/\u00a0/g, " ").trim() || null;
const unbracket = (v: string | undefined) => clean(clean(v)?.replace(/^\[([\s\S]*)\]$/, "$1"));
const OriginSchema = z.object({
  source_file: z.string().min(1),
  source_hash: z.string().regex(/^sha256:[a-f0-9]{64}$/),
  locator: z.discriminatedUnion("kind", [
    z.object({
      kind: z.literal("spreadsheet"),
      sheet: z.string().min(1),
      range: z.string().regex(/^[A-Z]+[1-9][0-9]*(?::[A-Z]+[1-9][0-9]*)?$/),
    }),
    z.object({
      kind: z.literal("csv"),
      row: z.number().int().min(2),
      columns: z.array(z.string().min(1)).min(1),
    }),
  ]),
});
const chunks = <T>(a: T[], n: number) =>
  Array.from({ length: Math.ceil(a.length / n) }, (_, i) => a.slice(i * n, (i + 1) * n));

async function mapLimit<T, R>(items: T[], n: number, fn: (x: T, i: number) => Promise<R>) {
  const out: R[] = [];
  let next = 0;
  await Promise.all(
    Array.from({ length: Math.min(n, items.length) }, async () => {
      while (next < items.length) {
        const i = next++;
        out[i] = await fn(items[i], i);
      }
    }),
  );
  return out;
}

function groupFeedbacks(rows: Row[]) {
  const byId = new Map<
    string,
    Omit<NewFeedbackEntry, "embedding"> & {
      aspects: { feedbackType: string | null; level2: string; level3: string | null }[];
      fallbackFeedbackType: string | null;
      origins: Origin[];
      rawClassifications: Record<string, unknown>[];
      originalRows: Row[];
    }
  >();
  for (const r of rows) {
    const id = clean(r["ID"]);
    const raw = clean(r["Customer Feedback"]);
    if (!id || !raw || raw.length < 5 || PLACEHOLDERS.has(raw.toLowerCase())) continue;
    let f = byId.get(id);
    if (!f) {
      const engine = clean(r["Engine Type"]);
      f = {
        feedbackExplorerId: id,
        source: clean(r["Source"]),
        brand: unbracket(r["Brand"]),
        salesDescription: unbracket(r["Sales Description"]),
        country: clean(r["Country"]),
        derivateCode: clean(r["Derivate (e-code)"]),
        engineType: engine === "BEVE" ? "BEV" : engine,
        rawFeedback: r["Customer Feedback"]!,
        aspects: [],
        fallbackFeedbackType: null,
        origins: [],
        rawClassifications: [],
        originalRows: [],
      };
      byId.set(id, f);
    }
    if (
      f.rawFeedback !== r["Customer Feedback"] ||
      f.country !== clean(r["Country"]) ||
      f.derivateCode !== clean(r["Derivate (e-code)"])
    )
      throw new Error("Conflicting parent fields for one Feedback Explorer ID");
    const origin = r.__bmwow_origin ? OriginSchema.parse(JSON.parse(r.__bmwow_origin)) : null;
    if (origin) f.origins.push(origin);
    f.originalRows.push(r);
    f.rawClassifications.push({
      feedback_type: r["Feedback Type"] ?? null,
      vfc_level2: r["Vfc level2 Name"] ?? null,
      vfc_level3: r["Vfc level3 Name"] ?? null,
      vfc_combined: r["Vfc level2 3 Name"] ?? null,
      locator: origin?.locator ?? null,
    });
    const feedbackType = clean(r["Feedback Type"]);
    const level2 = norm(r["Vfc level2 Name"]);
    if (level2 && level2 !== "no_class_found")
      f.aspects.push({ feedbackType, level2, level3: norm(r["Vfc level3 Name"]) });
    else f.fallbackFeedbackType ??= feedbackType;
  }
  return [...byId.values()];
}

function lookup(a: Aspect, tax: Taxonomy) {
  const vfcCategory = tax.vfc_category[a.level2] ?? "Unclassified";
  const issueType = a.level3 ? (tax.issue_type[a.level3] ?? "Unclassified") : "Unclassified";
  return { vfcCategory, issueType };
}

function sentiment(issueType: string, intensity: number) {
  const sign =
    issueType === "Praise"
      ? 1
      : issueType === "Feature Request" || issueType === "Unclassified"
        ? 0
        : -1;
  const magnitude = Math.round(Math.min(1, Math.max(0, intensity)) * 100) / 100;
  return {
    sentiment: sign > 0 ? "Positive" : sign < 0 ? "Negative" : "Neutral",
    sentimentScore: (sign * magnitude + 0).toFixed(2), // +0 turns -0 into 0
  };
}

function buildRecords(f: Feedback, tax: Taxonomy, e: Enrichment, enriched = true) {
  const {
    aspects,
    fallbackFeedbackType,
    origins: _origins,
    rawClassifications: _classifications,
    originalRows: _rows,
    ...entry
  } = f;
  const labelled: Omit<NewFeedbackAspect, "feedbackEntryId">[] = aspects.map((a, i) => {
    const { vfcCategory, issueType } = lookup(a, tax);
    return {
      feedbackType: a.feedbackType,
      vfcCategory,
      aspectTerm: a.level2,
      aspectLabelRaw: a.level3,
      issueType,
      quoteSnippet: null,
      ...sentiment(issueType, enriched ? e.scores[i] : 0),
      ...(!enriched ? { sentimentScore: null } : {}),
      extractionSource: "vfc_label",
    };
  });
  const extracted: Omit<NewFeedbackAspect, "feedbackEntryId">[] = aspects.length
    ? []
    : e.extracted.map((x) => ({
        feedbackType: fallbackFeedbackType,
        vfcCategory: x.vfc_category,
        aspectTerm: x.aspect_term.trim() || null,
        aspectLabelRaw: null,
        issueType: x.issue_type,
        quoteSnippet:
          x.quote_snippet.trim() && entry.rawFeedback.includes(x.quote_snippet.trim())
            ? x.quote_snippet.trim()
            : null, // never store a non-verbatim quote
        ...sentiment(x.issue_type, x.intensity),
        extractionSource: "llm",
      }));
  return { entry, aspects: [...labelled, ...extracted] };
}

function transform(rows: Row[], tax: Taxonomy, enrichments: Record<string, Enrichment>) {
  return groupFeedbacks(rows).map((f) => buildRecords(f, tax, enrichments[f.feedbackExplorerId]));
}

function selfCheck() {
  const row = (o: Row): Row => ({
    ID: "T-1",
    Source: "Source A",
    Brand: "[BMW]",
    "Sales Description": "[BMW 5 Series]",
    Country: "   ",
    "Derivate (e-code)": "G60",
    "Engine Type": "BEVE",
    "Feedback Type": "Likes",
    "Customer Feedback": " Lovely sound, but the screen keeps crashing. Wish it had CarPlay. ",
    "Vfc level2 Name": "Interior acoustics",
    "Vfc level3 Name": "Like: sound",
    ...o,
  });
  const rows = [
    row({}),
    row({
      "Feedback Type": "Defect",
      "Vfc level2 Name": "Touch\u00a0screen",
      "Vfc level3 Name": "Malfunction",
    }),
    row({
      "Feedback Type": "Wants",
      "Vfc level2 Name": "Apple CarPlay",
      "Vfc level3 Name": "Customer request: function",
    }),
    row({
      ID: "T-2",
      "Feedback Type": "",
      "Customer Feedback": "The seats hurt my back.",
      "Vfc level2 Name": "no_class_found",
      "Vfc level3 Name": "",
    }),
    row({
      ID: "T-2",
      "Feedback Type": "Defect",
      "Customer Feedback": "The seats hurt my back.",
      "Vfc level2 Name": "",
      "Vfc level3 Name": "",
    }),
    row({ ID: "T-3", "Customer Feedback": "ok" }),
  ];
  const tax: Taxonomy = {
    vfc_category: {
      "Interior acoustics": "Seats & Comfort",
      "Touch screen": "Infotainment & Connectivity",
      "Apple CarPlay": "Infotainment & Connectivity",
    },
    issue_type: {
      "Like: sound": "Praise",
      Malfunction: "Malfunction",
      "Customer request: function": "Feature Request",
    },
  };
  const out = transform(rows, tax, {
    "T-1": { scores: [0.6, 0.9, 0.7], extracted: [] },
    "T-2": {
      scores: [],
      extracted: [
        {
          vfc_category: "Seats & Comfort",
          issue_type: "Damage & Leaks",
          aspect_term: " seats ",
          quote_snippet: "seats hurt my back",
          intensity: 0.5,
        },
        {
          vfc_category: "Seats & Comfort",
          issue_type: "Praise",
          aspect_term: "x",
          quote_snippet: "invented quote",
          intensity: 0.5,
        },
      ],
    },
  });
  const [t1, t2] = out;

  // 1. three rows sharing an ID -> one entry, three aspects
  assert.equal(t1.entry.feedbackExplorerId, "T-1");
  assert.equal(t1.aspects.length, 3);
  // 2. cleaning
  assert.deepEqual(
    [
      t1.entry.engineType,
      t1.entry.brand,
      t1.entry.salesDescription,
      t1.entry.country,
      t1.entry.rawFeedback,
    ],
    [
      "BEV",
      "BMW",
      "BMW 5 Series",
      null,
      " Lovely sound, but the screen keeps crashing. Wish it had CarPlay. ",
    ],
  );
  // 3. provenance
  assert.deepEqual(t2.aspects[0], {
    feedbackType: "Defect",
    vfcCategory: "Seats & Comfort",
    aspectTerm: "seats",
    aspectLabelRaw: null,
    issueType: "Damage & Leaks",
    quoteSnippet: "seats hurt my back",
    sentiment: "Negative",
    sentimentScore: "-0.50",
    extractionSource: "llm",
  });
  assert.equal(t2.aspects[1].quoteSnippet, null); // non-verbatim quote dropped
  assert.ok(t1.aspects.every((a) => a.extractionSource === "vfc_label" && a.quoteSnippet === null));
  // 4. Malfunction 0.9 -> Negative -0.90 (NBSP-normalized label key)
  assert.deepEqual(
    [
      t1.aspects[1].aspectTerm,
      t1.aspects[1].vfcCategory,
      t1.aspects[1].sentiment,
      t1.aspects[1].sentimentScore,
    ],
    ["Touch screen", "Infotainment & Connectivity", "Negative", "-0.90"],
  );
  // 5. Feature Request -> Neutral 0.00 regardless of intensity
  assert.deepEqual([t1.aspects[2].sentiment, t1.aspects[2].sentimentScore], ["Neutral", "0.00"]);
  // 6. each aspect keeps its own Feedback Type
  assert.deepEqual(
    t1.aspects.map((a) => a.feedbackType),
    ["Likes", "Defect", "Wants"],
  );
  assert.deepEqual([t1.aspects[0].sentiment, t1.aspects[0].sentimentScore], ["Positive", "0.60"]);
  // 7. sub-5-char verbatim rejected entirely
  assert.equal(out.length, 2);
  assert.ok(!out.some((r) => r.entry.feedbackExplorerId === "T-3"));
}

async function main() {
  const { values } = parseArgs({
    options: {
      limit: { type: "string" },
      "self-check": { type: "boolean" },
      "no-enrichment": { type: "boolean" },
      migrate: { type: "boolean" },
      "csv-dir": { type: "string" },
      "env-file": { type: "string" },
      "taxonomy-file": { type: "string" },
      "proposals-file": { type: "string" },
    },
  });
  if (values["self-check"]) {
    selfCheck();
    console.log("self-check ok");
    return;
  }
  const limit = values.limit === undefined ? Infinity : Number(values.limit);
  if (!(Number.isInteger(limit) && limit > 0) && limit !== Infinity)
    throw new Error("--limit must be a positive integer");

  // An explicit file is authoritative. Missing files must never fall back to an
  // ambient production URL; omitted keys in that file remain omitted.
  let environment: Record<string, string | undefined>;
  if (values["env-file"]) environment = parseEnv(readFileSync(values["env-file"], "utf8"));
  else {
    try {
      process.loadEnvFile();
    } catch {} // optional when configured by the shell
    environment = process.env;
  }
  const { OPENAI_API_KEY, DATABASE_URL, DATABASE_URL_UNPOOLED } = environment;
  const noEnrichment = !!values["no-enrichment"];
  if ((!noEnrichment && !OPENAI_API_KEY) || !DATABASE_URL) {
    console.error("DATABASE_URL is required; provider mode also requires OPENAI_API_KEY");
    process.exit(1);
  }

  const openai = noEnrichment ? null : new OpenAI({ apiKey: OPENAI_API_KEY, maxRetries: 5 });
  const pool = new pg.Pool({ connectionString: DATABASE_URL });
  pool.on("error", () => console.error("feedback database connection failed"));
  const csvDir = values["csv-dir"] ?? CSV_DIR;
  const taxonomyPath = values["taxonomy-file"] ?? TAXONOMY_PATH;
  const proposalsPath = values["proposals-file"] ?? "data/feedbacks/taxonomy-proposals.json";
  const usage = { input: 0, output: 0, embed: 0 };

  async function llm<S extends z.ZodType>(
    schema: S,
    effort: "low" | "high",
    instructions: string,
    input: string,
  ) {
    if (!openai) throw new Error("Provider calls are disabled in no-enrichment mode");
    const r = await openai.responses.parse({
      model: MODEL,
      reasoning: { effort },
      instructions,
      input,
      text: { format: zodTextFormat(schema, "result") },
    });
    usage.input += r.usage?.input_tokens ?? 0;
    usage.output += r.usage?.output_tokens ?? 0;
    if (!r.output_parsed) throw new Error("model returned no parsed output");
    return r.output_parsed as z.infer<S>;
  }

  try {
    if (values.migrate) {
      if (!DATABASE_URL_UNPOOLED) throw new Error("Migration requires DATABASE_URL_UNPOOLED");
      if (new URL(DATABASE_URL_UNPOOLED).hostname.includes("-pooler"))
        throw new Error("Migration requires a direct connection");
      const migrationPool = new pg.Pool({ connectionString: DATABASE_URL_UNPOOLED });
      try {
        const client = await migrationPool.connect();
        try {
          await client.query("BEGIN");
          await client.query(readFileSync("migrations/0000_init.sql", "utf8"));
          await client.query(readFileSync("migrations/0001_feedback_provenance.sql", "utf8"));
          await client.query("COMMIT");
        } catch (error) {
          await client.query("ROLLBACK");
          throw error;
        } finally {
          client.release();
        }
      } finally {
        await migrationPool.end();
      }
    }
    const history = (
      await pool.query("SELECT to_regclass('public.feedback_revisions') AS relation")
    ).rows[0].relation;
    if (!history) throw new Error("Apply the feedback provenance migration before importing");

    const files = readdirSync(csvDir)
      .filter((f) => f.endsWith(".csv"))
      .sort();
    const rows = files.flatMap((f) => {
      const bytes = readFileSync(`${csvDir}/${f}`);
      const sourceHash = "sha256:" + createHash("sha256").update(bytes).digest("hex");
      const parsed = parse(bytes, { columns: true, bom: true }) as Row[];
      return parsed.map((row, i) => ({
        ...row,
        __bmwow_origin:
          row.__bmwow_origin ??
          JSON.stringify({
            source_file: `${csvDir}/${f}`,
            source_hash: sourceHash,
            locator: { kind: "csv", row: i + 2, columns: Object.keys(row) },
          }),
      }));
    });
    const feedbacks = groupFeedbacks(rows);
    console.log(
      `read ${rows.length} rows from ${files.length} files -> ${feedbacks.length} unique feedbacks`,
    );

    // Pass 1: classify only taxonomy labels missing from the committed file.
    const tax = TaxonomySchema.parse({
      vfc_category: {},
      issue_type: {},
      ...(existsSync(taxonomyPath) ? JSON.parse(readFileSync(taxonomyPath, "utf8")) : {}),
    });
    const proposed = TaxonomySchema.parse({
      vfc_category: {},
      issue_type: {},
      ...(existsSync(proposalsPath) ? JSON.parse(readFileSync(proposalsPath, "utf8")) : {}),
    });
    const aspects = feedbacks.flatMap((f) => f.aspects);
    const missing2 = [...new Set(aspects.map((a) => a.level2))].filter(
      (l) => !Object.hasOwn(tax.vfc_category, l),
    );
    const missing3 = [...new Set(aspects.flatMap((a) => a.level3 ?? []))].filter(
      (l) => !Object.hasOwn(tax.issue_type, l),
    );
    console.log(
      `taxonomy: classifying ${missing2.length} level2 + ${missing3.length} level3 labels`,
    );
    const classify = <E extends readonly [string, ...string[]]>(
      labels: string[],
      allowed: E,
      what: string,
      into: Record<string, E[number]>,
    ) =>
      mapLimit(chunks(labels, 30), 25, async (batch) => {
        const { labels: out } = await llm(
          z.object({ labels: z.array(z.enum(allowed)) }),
          "high",
          `You bucket BMW customer-feedback taxonomy labels. Each label is a ${what}. Assign each label exactly one bucket from the allowed list (use "Unclassified" only if nothing fits). Return the buckets in "labels" in the same order as the input, exactly one per input label.\nAllowed buckets: ${allowed.join(" | ")}`,
          batch.map((l, i) => `${i + 1}. ${l}`).join("\n"),
        );
        if (out.length !== batch.length)
          throw new Error(`taxonomy batch: got ${out.length} labels for ${batch.length}`);
        batch.forEach((l, i) => (into[l] = out[i]));
      });
    const sortKeys = <V>(o: Record<string, V>) =>
      Object.fromEntries(Object.entries(o).sort(([a], [b]) => a.localeCompare(b)));
    try {
      if (!noEnrichment)
        await classify(
          missing2,
          VFC_CATEGORIES,
          "vehicle component / feature aspect (VFC level 2)",
          proposed.vfc_category,
        );
      if (!noEnrichment)
        await classify(
          missing3,
          ISSUE_TYPES,
          "kind of customer reaction or issue (VFC level 3), e.g. praise, malfunction, wish",
          proposed.issue_type,
        );
    } finally {
      if (!noEnrichment && (missing2.length || missing3.length)) {
        mkdirSync(dirname(proposalsPath), { recursive: true });
        writeFileSync(
          proposalsPath,
          JSON.stringify(
            {
              vfc_category: sortKeys(proposed.vfc_category),
              issue_type: sortKeys(proposed.issue_type),
            },
            null,
            2,
          ) + "\n",
        );
      }
    }

    const processing = {
      preprocessing: "feedback-v3",
      enrichment_model: noEnrichment ? "none" : MODEL,
      prompt_version: noEnrichment ? "none" : "feedback-enrichment-v1",
      taxonomy_hash: hash(tax),
      embedding_model: noEnrichment ? "none" : EMBED_MODEL,
      embedding_dimensions: noEnrichment ? 0 : 1536,
    };
    const versions = new Map(
      feedbacks.map((f) => [
        f.feedbackExplorerId,
        provenance(
          f.feedbackExplorerId,
          f.originalRows,
          f.rawFeedback,
          processing,
          f.origins,
          f.rawClassifications,
        ),
      ]),
    );
    const existing = new Map(
      (
        await pool.query<{
          feedback_explorer_id: string;
          revision_id: string | null;
          provenance: FeedbackProvenance | null;
          embedding: string | null;
        }>(
          "SELECT feedback_explorer_id, revision_id, provenance, embedding::text FROM feedback_entries",
        )
      ).rows.map((r) => [r.feedback_explorer_id, r]),
    );
    const remaining = feedbacks.filter(
      (f) =>
        !complete(
          existing.get(f.feedbackExplorerId)?.provenance ?? null,
          versions.get(f.feedbackExplorerId)!,
        ),
    );
    const todo = remaining.slice(0, limit);
    const stats = { written: 0, aspects: 0, failures: 0 };
    const failedIds: string[] = [];
    const fail = (id: string, _e: unknown) => {
      console.error("feedback enrichment or persistence failed; see the private failure report");
      stats.failures++;
      failedIds.push(id);
    };

    async function enrich(f: Feedback): Promise<Enrichment> {
      if (noEnrichment) return { scores: [], extracted: [] };
      const n = f.aspects.length;
      const instructions = n
        ? `You read one BMW customer feedback verbatim and ${n} aspect(s) already identified in it. For each aspect, in the given order, rate its intensity from 0 to 1: how strongly the customer expresses it (0 = barely or mildly mentioned, 1 = extremely strong). Return exactly ${n} numbers in "scores" and an empty "extracted" array.`
        : `You read one BMW customer feedback verbatim. Extract every distinct aspect of the vehicle or service the customer comments on. For each: vfc_category and issue_type from the allowed values ("Praise" for positive remarks, "Feature Request" for wishes, "Unclassified" if nothing fits), aspect_term (a short noun phrase, 1-4 words), quote_snippet (an exact substring of the verbatim supporting it), intensity from 0 to 1 (how strongly it is expressed). Return an empty "scores" array.`;
      const input = n
        ? `Verbatim:\n${f.rawFeedback}\n\nAspects:\n${f.aspects
            .map((a, i) => {
              const { vfcCategory, issueType } = lookup(a, tax);
              return `${i + 1}. category: ${vfcCategory}; aspect: ${a.level2}; raw issue label: ${a.level3 ?? "(none)"}; issue_type: ${issueType}`;
            })
            .join("\n")}`
        : `Verbatim:\n${f.rawFeedback}`;
      for (let attempt = 1; ; attempt++) {
        try {
          const r = await llm(EnrichmentSchema, "low", instructions, input);
          if (n && r.scores.length !== n)
            throw new Error(`expected ${n} scores, got ${r.scores.length}`);
          if ([...r.scores, ...r.extracted.map((x) => x.intensity)].some((s) => s < 0 || s > 1))
            throw new Error("intensity outside 0..1");
          // empty extraction is retried, then accepted so the entry is still searchable
          if (!n && !r.extracted.length && attempt < 3) throw new Error("no aspects extracted");
          return n ? { scores: r.scores, extracted: [] } : { scores: [], extracted: r.extracted };
        } catch (e) {
          if (e instanceof OpenAI.APIError || attempt >= 3) throw e; // SDK already retried API errors
        }
      }
    }

    const chunked = chunks(todo, 200);
    for (const [ci, batch] of chunked.entries()) {
      let vectors: (number[] | null)[];
      try {
        vectors = batch.map((f) => {
          const current = existing.get(f.feedbackExplorerId);
          return current?.embedding &&
            reusableEmbedding(current.provenance, versions.get(f.feedbackExplorerId)!)
            ? (JSON.parse(current.embedding) as number[])
            : null;
        });
        const missing = batch.map((_, i) => i).filter((i) => !vectors[i]);
        if (openai && missing.length) {
          const r = await openai.embeddings.create({
            model: EMBED_MODEL,
            dimensions: 1536,
            input: missing.map((i) => batch[i].rawFeedback),
          });
          usage.embed += r.usage.total_tokens;
          const fresh = [...r.data].sort((a, b) => a.index - b.index).map((d) => d.embedding);
          if (fresh.length !== missing.length || fresh.some((v) => v.length !== 1536))
            throw new Error("Embedding response does not match the requested count/dimensions");
          missing.forEach((index, j) => {
            vectors[index] = fresh[j];
          });
        }
      } catch (e) {
        for (const f of batch) fail(f.feedbackExplorerId, e);
        continue;
      }
      await mapLimit(batch, 25, async (f, i) => {
        try {
          const { entry, aspects } = buildRecords(f, tax, await enrich(f), !noEnrichment);
          const client = await pool.connect();
          try {
            await storeRevision(
              client,
              entry,
              aspects,
              versions.get(f.feedbackExplorerId)!,
              vectors[i],
              existing.get(f.feedbackExplorerId)?.revision_id ?? null,
            );
          } finally {
            client.release();
          }
          stats.written++;
          stats.aspects += aspects.length;
        } catch (e) {
          fail(f.feedbackExplorerId, e);
        }
      });
      console.log(
        `chunk ${ci + 1}/${chunked.length}: ${stats.written} written, ${stats.failures} failed`,
      );
    }

    const cost = (usage.input * 0.1 + usage.output * 0.5 + usage.embed * 0.13) / 1e6;
    console.log(
      [
        `rows read:         ${rows.length}`,
        `rows excluded:     ${rows.length - feedbacks.reduce((sum, f) => sum + f.originalRows.length, 0)}`,
        `unique feedbacks:  ${feedbacks.length}`,
        `skipped (done):    ${feedbacks.length - remaining.length}`,
        `entries written:   ${stats.written}`,
        `aspects written:   ${stats.aspects}`,
        `failures:          ${stats.failures}`,
        `tokens:            ${usage.input} in / ${usage.output} out / ${usage.embed} embedding`,
        `estimated cost:    $${cost.toFixed(4)}`,
      ].join("\n"),
    );
    if (stats.failures) {
      mkdirSync("data/feedbacks", { recursive: true });
      writeFileSync("data/feedbacks/import-failures.json", JSON.stringify({ failedIds }, null, 2));
      process.exitCode = 1;
    }
  } finally {
    await pool.end();
  }
}

main().catch(() => {
  console.error("Feedback import failed; check configuration, source consistency and migrations");
  process.exit(1);
});
