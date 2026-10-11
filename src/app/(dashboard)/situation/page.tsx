import Link from "next/link";
import { connection } from "next/server";
import { Suspense } from "react";
import { sentence, VerdictLegend, VerdictStrip } from "@/components/situation/parts";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { int, mood } from "@/lib/format";
import { cn } from "@/lib/utils";
import { listCars, type Car } from "@/server/analysis/queries";
import { listRuns, type RunSummary } from "@/server/situation/queries";

export default function SituationPage() {
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Situation analysis</h1>
          <p className="text-sm text-muted-foreground">
            Requirements for each car's successor, per market.
          </p>
        </div>
        <VerdictLegend />
      </div>
      <Suspense fallback={<Skeleton className="h-48 w-full rounded-xl" />}>
        <Cars />
      </Suspense>
    </>
  );
}

async function Cars() {
  await connection(); // keep the DB out of the build-time prerender
  const [runs, feedback] = await Promise.all([listRuns(), listCars()]);
  if (!runs.length) {
    return (
      <p className="text-sm text-muted-foreground">
        No stored runs yet. Export one with python/scripts/export_analysis.py.
      </p>
    );
  }
  const series = Map.groupBy(runs, (r) => r.modelCode[0]);
  return [...series].reverse().map(([letter, seriesRuns]) => (
    <section key={letter} className="flex flex-col gap-3">
      <h2 className="text-sm font-medium text-muted-foreground">{letter} series</h2>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {[...Map.groupBy(seriesRuns, (r) => r.modelCode)].map(([code, group]) => (
          <CarCard
            key={code}
            code={code}
            runs={group}
            car={feedback.find((c) => c.derivate === code)}
          />
        ))}
      </div>
    </section>
  ));
}

function CarCard({ code, runs, car }: { code: string; runs: RunSummary[]; car?: Car }) {
  const lead = runs.reduce((a, b) => (b.requirements > a.requirements ? b : a));
  const m = mood(car?.net ?? null);
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="text-3xl font-semibold tracking-tight">
          <Link href={`/situation/${code}?region=${lead.region}`} className="hover:underline">
            {code}
          </Link>
        </CardTitle>
        <CardDescription>
          {runs[0].modelName ?? code}
          <span className="block text-xs">
            {car ? (
              <>
                {int(car.feedback)} feedback ·{" "}
                <span className={cn("font-medium", m.className)}>{m.label}</span>
              </>
            ) : (
              "No customer feedback"
            )}
          </span>
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <ul className="flex flex-col gap-1">
          {runs.map((r) => (
            <li key={r.runId}>
              <Link
                href={`/situation/${code}?region=${r.region}`}
                className="grid grid-cols-[3rem_1fr_4.5rem] items-center gap-3 rounded-lg px-2 py-1.5 text-sm transition-colors hover:bg-muted/50"
              >
                <Badge variant="secondary" className="justify-self-start">
                  {r.region === "ALL" ? "All" : r.region}
                </Badge>
                <VerdictStrip counts={r.verdicts} />
                <span className="text-right tabular-nums">
                  <span className="font-medium">{r.requirements}</span>{" "}
                  <span className="text-xs text-muted-foreground">req.</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
        {lead.topFeature && (
          <p className="truncate text-sm">
            <span className="text-xs text-muted-foreground">
              #1 ({lead.region === "ALL" ? "all" : lead.region}){" "}
            </span>
            <span className="font-medium">{sentence(lead.topFeature)}</span>
          </p>
        )}
      </CardContent>
    </Card>
  );
}
