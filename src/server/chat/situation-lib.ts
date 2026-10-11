// Pure helpers for the situation-analysis part of the chat; no DB or Next imports (runs under vitest).
import { z } from "zod";

/** A /situation page: the overview (no car) or one car's run in a region ("ALL" = all regions). */
export type SituationPage = {
  derivate: string | null;
  region: "ALL" | "EU" | "US" | "CN" | null;
  feature: string | null;
};

const pageSchema = z.object({
  view: z.literal("situation"),
  derivate: z
    .string()
    .regex(/^[A-Z0-9]{2,8}$/)
    .nullish()
    .catch(null)
    .transform((v) => v ?? null),
  region: z
    .enum(["ALL", "EU", "US", "CN"])
    .nullish()
    .catch(null)
    .transform((v) => v ?? null),
  feature: z
    .string()
    .regex(/^[a-z0-9_:]{1,64}$/)
    .nullish()
    .catch(null)
    .transform((v) => v ?? null),
});

/** Untrusted page context → a situation page, or null when the user is not on /situation. */
export function parseSituationPage(page: unknown): SituationPage | null {
  const p = pageSchema.safeParse(page ?? {});
  if (!p.success) return null;
  const { derivate, region, feature } = p.data;
  return { derivate, region, feature };
}

/** The feedback filter a situation region maps to: US and CN are countries; EU/ALL span many. */
export const feedbackCountry = (region: SituationPage["region"]) =>
  region === "US" || region === "CN" ? region : null;

/** "fb:evidence:bmw-feedback:G60-0042" → "G60-0042", the id form the chat cites. */
export const shortFeedbackId = (sourceId: string) =>
  sourceId
    .replace(/^fb:/, "")
    .replace(/^evidence:/, "")
    .replace(/^bmw-feedback:/, "");

export const regionLabel = (region: string | null) =>
  !region ? "default region" : region === "ALL" ? "all regions" : region;
