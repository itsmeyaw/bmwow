// Pure helpers for the chat agent; no DB or Next imports so they run under vitest.
import { z } from "zod";
import { EU27 } from "../../lib/markets"; // relative: vitest has no @ alias
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

// ponytail: GB, NO, CH, … fall into RoW; confirm against the sales workbook's market definition.
/** ISO country → sales market code used by the `sales` table. */
export function salesMarket(country: string | null): string | null {
  if (!country) return null;
  if (EU27.has(country)) return "EU";
  return country === "US" || country === "CN" ? country : "RoW";
}

export const TOPIC_MAX = 120;

/**
 * Public web query: a short topic plus the public car name and country.
 * Strips anything beyond plain words/punctuation so pasted verbatims stay short and inert.
 * Returns null when nothing usable is left.
 */
export function webQuery(
  topic: string,
  carName: string | null,
  country: string | null,
): string | null {
  const t = topic
    .replace(/[^\p{L}\p{N} .,&/'()+-]/gu, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, TOPIC_MAX)
    .trim();
  if (!t) return null;
  const car = !carName ? "BMW" : /^bmw\b/i.test(carName) ? carName : `BMW ${carName}`;
  return [car, t, country && `in ${country}`].filter(Boolean).join(" ");
}

/** Reciprocal rank fusion of ranked id lists, best first. */
export function rrf(lists: string[][], k = 60): string[] {
  const score = new Map<string, number>();
  for (const list of lists)
    list.forEach((id, i) => score.set(id, (score.get(id) ?? 0) + 1 / (k + i + 1)));
  return [...score].sort((a, b) => b[1] - a[1]).map(([id]) => id);
}
