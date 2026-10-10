import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import pg from "pg";
import {
  complete,
  hash,
  provenance,
  reusableEmbedding,
  storeRevision,
  type Processing,
} from "./feedback-provenance";

const processing: Processing = {
  preprocessing: "synthetic-v1",
  enrichment_model: "none",
  prompt_version: "none",
  taxonomy_hash: hash({ invented: "Seats & Comfort" }),
  embedding_model: "none",
  embedding_dimensions: 0,
};
const version = (text = "Invented seat feedback", p = processing) =>
  provenance(
    "synthetic-one",
    { text, label: "invented" },
    text,
    p,
    [
      {
        source_file: "invented.xlsx",
        source_hash: hash("file"),
        locator: { kind: "spreadsheet", sheet: "Invented", range: "A2:D2" },
      },
    ],
    [{ feedback_type: "Likes", vfc_level2: "invented" }],
  );

test("signatures are deterministic and respond to text and processing changes", () => {
  assert.equal(hash({ a: 1, b: 2 }), hash({ b: 2, a: 1 }));
  assert.deepEqual(version(), version());
  assert.equal(complete(version(), version()), true);
  assert.equal(complete(null, version()), false);
  assert.equal(complete(version(), version("Changed invented feedback")), false);
  assert.equal(
    complete(version(), version(undefined, { ...processing, taxonomy_hash: hash("new mapping") })),
    false,
  );
  assert.equal(
    complete(version(), version(undefined, { ...processing, prompt_version: "new prompt" })),
    false,
  );
});

test("embedding reuse requires the same text and embedding/preprocessing specification", () => {
  assert.equal(
    reusableEmbedding(
      version(),
      version(undefined, { ...processing, taxonomy_hash: hash("new mapping") }),
    ),
    true,
  );
  for (const p of [
    { ...processing, preprocessing: "new" },
    { ...processing, embedding_model: "new" },
    { ...processing, embedding_dimensions: 1536 },
  ])
    assert.equal(reusableEmbedding(version(), version(undefined, p)), false);
  assert.equal(reusableEmbedding(version(), version("Changed invented feedback")), false);
});

// Opt in with an empty, disposable database. No production URL is read or migrations applied by default.
test(
  "transactional refresh, history, replay, stale writes and rollback",
  { skip: !process.env.BMWOW_TEST_DATABASE_URL },
  async () => {
    const pool = new pg.Pool({ connectionString: process.env.BMWOW_TEST_DATABASE_URL });
    const client = await pool.connect();
    try {
      const present = (
        await client.query("SELECT to_regclass('public.feedback_entries') AS relation")
      ).rows[0].relation;
      assert.equal(present, null, "Integration tests require an empty disposable database");
      for (const file of ["0000_init.sql", "0001_feedback_provenance.sql"])
        await client.query(readFileSync(`migrations/${file}`, "utf8"));
      const entry = {
        feedbackExplorerId: "synthetic-one",
        source: "Invented source",
        brand: "Invented",
        salesDescription: "Invented",
        country: "US",
        derivateCode: "G70",
        engineType: null,
        rawFeedback: "Invented seat feedback",
      };
      const aspects = [
        {
          feedbackType: "Likes",
          vfcCategory: "Seats & Comfort",
          aspectTerm: "invented",
          aspectLabelRaw: "invented praise",
          issueType: "Praise",
          quoteSnippet: null,
          sentiment: "Positive",
          sentimentScore: null,
          extractionSource: "vfc_label",
        },
      ];
      const original = version();
      assert.equal(await storeRevision(client, entry, aspects, original, null, null), "written");
      assert.equal(await storeRevision(client, entry, aspects, original, null, null), "skipped");
      const first = (await client.query("SELECT id,created_at FROM feedback_entries")).rows[0];
      const changed = version("Changed invented feedback");
      await assert.rejects(
        storeRevision(
          client,
          { ...entry, rawFeedback: "Changed invented feedback" },
          aspects,
          changed,
          null,
          null,
        ),
        /changed during import/,
      );
      assert.equal(
        await storeRevision(
          client,
          { ...entry, rawFeedback: "Changed invented feedback" },
          aspects,
          changed,
          null,
          original.revision_id,
        ),
        "written",
      );
      assert.equal((await client.query("SELECT id FROM feedback_entries")).rows[0].id, first.id);
      assert.equal(
        (await client.query("SELECT count(*)::int AS n FROM feedback_revisions")).rows[0].n,
        2,
      );
      const broken = version("Broken invented refresh");
      await assert.rejects(
        storeRevision(
          client,
          entry,
          [{ ...aspects[0], sentiment: "invalid" }],
          broken,
          null,
          changed.revision_id,
        ),
      );
      assert.equal(
        (await client.query("SELECT revision_id FROM feedback_entries")).rows[0].revision_id,
        changed.revision_id,
      );
      assert.equal(
        (await client.query("SELECT count(*)::int AS n FROM feedback_revisions")).rows[0].n,
        2,
      );
      assert.equal(
        (await client.query("SELECT count(*)::int AS n FROM feedback_aspects")).rows[0].n,
        1,
      );
      assert.equal(
        await storeRevision(client, entry, [], original, null, changed.revision_id),
        "written",
      );
      assert.equal(
        (
          await client.query("SELECT created_at FROM feedback_entries")
        ).rows[0].created_at.toISOString(),
        first.created_at.toISOString(),
      );
      assert.equal(
        (await client.query("SELECT count(*)::int AS n FROM feedback_aspects")).rows[0].n,
        1,
      );
    } finally {
      client.release();
      await pool.end();
    }
  },
);
