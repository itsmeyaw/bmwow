import Link from "next/link";
import { connection } from "next/server";
import { Suspense } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { listRuns, type RunSummary } from "@/server/situation/queries";

export default function SituationPage() {
  return (
    <>
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Situation analysis</h1>
        <p className="text-sm text-muted-foreground">
          Requirement recommendations for each car's successor, per region: our current model,
          competitors, customer feedback and trends, with every number traced to its source.
        </p>
      </div>
      <Suspense fallback={<Skeleton className="h-48 w-full rounded-xl" />}>
        <Cars />
      </Suspense>
    </>
  );
}

async function Cars() {
  await connection(); // keep the DB out of the build-time prerender
  const runs = await listRuns();
  if (!runs.length) {
    return (
      <p className="text-sm text-muted-foreground">
        No stored runs yet. Export one with python/scripts/export_analysis.py.
      </p>
    );
  }
  const cars = Map.groupBy(runs, (r) => r.modelCode);
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {[...cars].map(([code, group]) => (
        <CarCard key={code} code={code} runs={group} />
      ))}
    </div>
  );
}

function CarCard({ code, runs }: { code: string; runs: RunSummary[] }) {
  const lead = runs.reduce((a, b) => (b.requirements > a.requirements ? b : a));
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="text-3xl font-semibold tracking-tight">
          <Link href={`/situation/${code}?region=${lead.region}`} className="hover:underline">
            {code}
          </Link>
        </CardTitle>
        <CardDescription>{runs[0].modelName ?? code}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <ul className="flex flex-col gap-2">
          {runs.map((r) => (
            <li key={r.runId}>
              <Link
                href={`/situation/${code}?region=${r.region}`}
                className="flex items-center justify-between gap-3 rounded-lg border p-2 text-sm transition-colors hover:bg-muted/50"
              >
                <span className="flex items-center gap-2">
                  <Badge variant="secondary">{r.region === "ALL" ? "All regions" : r.region}</Badge>
                  <span className="text-muted-foreground">{r.features} features analysed</span>
                </span>
                <span className="font-medium tabular-nums">
                  {r.requirements} requirement{r.requirements === 1 ? "" : "s"}
                </span>
              </Link>
            </li>
          ))}
        </ul>
        {lead.topRequirement && (
          <div className="text-sm">
            <p className="text-xs text-muted-foreground">
              #1 recommendation ({lead.region === "ALL" ? "all regions" : lead.region})
            </p>
            <p className="line-clamp-3">{lead.topRequirement}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
