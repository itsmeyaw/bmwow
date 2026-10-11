import { undoDecision } from "@/server/situation/decisions";

/** POST {id} → marks a PM decision as undone (the decision log keeps it). */
export async function POST(req: Request) {
  const { id } = (await req.json().catch(() => ({}))) as { id?: unknown };
  if (typeof id !== "string") return Response.json({ ok: false }, { status: 400 });
  return Response.json({ ok: await undoDecision(id) });
}
