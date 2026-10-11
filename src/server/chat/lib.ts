// Pure helpers for the chat agent; no DB or Next imports so they run under vitest.
import { z } from "zod";
import type { Scope } from "@/server/analysis/queries";

const code = (re: RegExp) =>
  z
    .string()
    .regex(re)
    .nullish()
    .catch(null)
    .transform((v) => v ?? null);

/** What the client may say about the page it is on: URL values, nothing else. */
const pageSchema = z
  .object({
    derivate: code(/^[A-Z0-9]{2,8}$/),
    region: code(/^[A-Z]{2}$/),
    engine: z
      .enum(["BEV", "PHEV", "ICE"])
      .nullish()
      .catch(null)
      .transform((v) => v ?? null),
  })
  .catch({ derivate: null, region: null, engine: null });

/** Untrusted page context → Scope. Anything malformed becomes `null` (= all). */
export function parseScope(page: unknown): Scope {
  const p = pageSchema.parse(page ?? {});
  return { derivate: p.derivate, country: p.region, engine: p.engine };
}

const EU27 = new Set(
  "AT BE BG HR CY CZ DK EE FI FR DE GR IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split(" "),
);

// ponytail: GB, NO, CH, … fall into RoW; confirm against the sales workbook's market definition.
/** ISO country → sales market code used by the `sales` table. */
export function salesMarket(country: string | null): string | null {
  if (!country) return null;
  if (EU27.has(country)) return "EU";
  return country === "US" || country === "CN" ? country : "RoW";
}

/** Reciprocal rank fusion of ranked id lists, best first. */
export function rrf(lists: string[][], k = 60): string[] {
  const score = new Map<string, number>();
  for (const list of lists)
    list.forEach((id, i) => score.set(id, (score.get(id) ?? 0) + 1 / (k + i + 1)));
  return [...score].sort((a, b) => b[1] - a[1]).map(([id]) => id);
}
