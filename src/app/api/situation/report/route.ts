import { listDecisions } from "@/server/situation/decisions";
import { listFeatures, resolveRun } from "@/server/situation/queries";
import { buildReport } from "@/server/situation/report";

/** GET ?derivate=G60&region=US → the run's recommendations adapted by the PM's decisions, as PDF. */
export async function GET(req: Request) {
  const params = new URL(req.url).searchParams;
  const derivate = params.get("derivate") ?? "";
  const region = params.get("region");
  if (!/^[A-Z0-9]{2,8}$/.test(derivate) || (region && !/^(ALL|EU|US|CN)$/.test(region))) {
    return new Response("Unknown car or region.", { status: 400 });
  }
  const run = await resolveRun(derivate, region);
  if (!run) return new Response("No stored run for this car and region.", { status: 404 });
  const [features, decisions] = await Promise.all([
    listFeatures(run.runId),
    listDecisions(run.runId),
  ]);
  const pdf = await buildReport(run, features, decisions);
  const name = `requirements-${run.modelCode}-${run.region}-${new Date().toISOString().slice(0, 10)}.pdf`;
  return new Response(new Uint8Array(pdf), {
    headers: {
      "content-type": "application/pdf",
      "content-disposition": `attachment; filename="${name}"`,
      "cache-control": "no-store",
    },
  });
}
