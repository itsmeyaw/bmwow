// Mirrors migrations/0000_init.sql (DDL is the source of truth for indexes/constraints).
import { sql } from "drizzle-orm";
import { customType, numeric, pgTable, text, timestamp, uuid, vector } from "drizzle-orm/pg-core";

const tsvector = customType<{ data: string }>({
  dataType: () => "tsvector",
});

export const feedbackEntries = pgTable("feedback_entries", {
  id: uuid("id").primaryKey().defaultRandom(),
  feedbackExplorerId: text("feedback_explorer_id").notNull().unique(),
  source: text("source"),
  brand: text("brand"),
  salesDescription: text("sales_description"),
  country: text("country"),
  derivateCode: text("derivate_code"),
  engineType: text("engine_type"),
  rawFeedback: text("raw_feedback").notNull(),
  embedding: vector("embedding", { dimensions: 1536 }),
  searchTsv: tsvector("search_tsv").generatedAlwaysAs(sql`to_tsvector('english', raw_feedback)`),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

export const feedbackAspects = pgTable("feedback_aspects", {
  id: uuid("id").primaryKey().defaultRandom(),
  feedbackEntryId: uuid("feedback_entry_id")
    .notNull()
    .references(() => feedbackEntries.id, { onDelete: "cascade" }),
  feedbackType: text("feedback_type"),
  vfcCategory: text("vfc_category").notNull(),
  aspectTerm: text("aspect_term"),
  aspectLabelRaw: text("aspect_label_raw"),
  issueType: text("issue_type").notNull(),
  quoteSnippet: text("quote_snippet"),
  sentiment: text("sentiment").notNull(),
  sentimentScore: numeric("sentiment_score", { precision: 3, scale: 2 }),
  extractionSource: text("extraction_source").notNull(),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

export type NewFeedbackEntry = typeof feedbackEntries.$inferInsert;
export type NewFeedbackAspect = typeof feedbackAspects.$inferInsert;
