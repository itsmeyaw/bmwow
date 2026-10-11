import "server-only";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { sql } from "drizzle-orm";
import { db } from "@/server/db/client";
import { rows } from "@/server/analysis/queries";
import type { Decision, DecisionAction } from "./apply-decisions";

/**
 * PM decisions about a stored run (table analysis_decisions). The only writes the situation
 * chat can make; the recorded run (analysis_*) is never changed.
 */

let ready: Promise<void> | null = null;

/** Creates the table on first use (idempotent DDL from migrations/0003). */
function ensureTable() {
  ready ??= readFile(
    path.join(process.cwd(), "migrations", "0003_analysis_decisions.sql"),
    "utf8",
  ).then(async (ddl) => {
    await db.execute(sql.raw(ddl));
  });
  ready.catch(() => (ready = null)); // retry on the next call after a failure
  return ready;
}

const COLUMNS = sql`id::text as id, req_id as "reqId", attribute, action, operator, value, unit,
  reason, created_at::text as "createdAt", undone_at::text as "undoneAt"`;

export async function listDecisions(runId: string): Promise<Decision[]> {
  await ensureTable();
  return rows<Decision>(sql`
    select ${COLUMNS} from analysis_decisions
    where run_id = ${runId} order by created_at`);
}

export type NewDecision = {
  runId: string;
  attribute: string;
  action: DecisionAction;
  operator?: string | null;
  value?: number | null;
  unit?: string | null;
  reason: string;
};

/** Records a decision after checking the feature exists in the run; returns it with its REQ id. */
export async function addDecision(d: NewDecision): Promise<Decision> {
  await ensureTable();
  const [feature] = await rows<{ reqId: string | null }>(sql`
    select r.req_id as "reqId"
    from analysis_features f
    left join analysis_requirements r on r.run_id = f.run_id and r.attribute = f.attribute
    where f.run_id = ${d.runId} and f.attribute = ${d.attribute}`);
  if (!feature) throw new Error(`Feature ${d.attribute} is not in run ${d.runId}.`);
  const [row] = await rows<Decision>(sql`
    insert into analysis_decisions (run_id, req_id, attribute, action, operator, value, unit, reason)
    values (${d.runId}, ${feature.reqId}, ${d.attribute}, ${d.action}, ${d.operator ?? null},
            ${d.value ?? null}, ${d.unit ?? null}, ${d.reason.slice(0, 500)})
    returning ${COLUMNS}`);
  return row;
}

/** Marks a decision as undone (kept for the log). Returns false if it was unknown or already undone. */
export async function undoDecision(id: string): Promise<boolean> {
  await ensureTable();
  if (!/^[0-9a-f-]{36}$/.test(id)) return false;
  const done = await rows<{ id: string }>(sql`
    update analysis_decisions set undone_at = now()
    where id = ${id}::uuid and undone_at is null returning id::text`);
  return done.length > 0;
}
