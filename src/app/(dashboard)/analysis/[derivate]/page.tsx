import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { AspectSheet, ScopeSelect } from "@/components/car-controls";
import { AspectDetail, Bar, hrefWith, Kpi, one, type Search } from "@/components/feedback";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { countryName, int, mood, pct, signed, signTone } from "@/lib/format";
import { EU27, marketCountries } from "@/lib/markets";
import { cn } from "@/lib/utils";
import {
  getRanking,
  getScopeOptions,
  getSummary,
  listCars,
  type Ranking,
  type Scope,
} from "@/server/analysis/queries";

export default function CarPage(props: PageProps<"/analysis/[derivate]">) {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full rounded-xl" />}>
      <CarView {...props} />
    </Suspense>
  );
}

async function CarView({ params, searchParams }: PageProps<"/analysis/[derivate]">) {
  const { derivate } = await params;
  const sp: Search = await searchParams;
  const region = one(sp.region); // a country code or "EU"
  const scope: Scope = {
    derivate,
    country: null,
    engine: one(sp.engine),
    countries: region ? marketCountries(region) : null,
  };
  const [car] = (await listCars()).filter((c) => c.derivate === derivate);
  if (!car) notFound();

  const [options, summary, ranking] = await Promise.all([
    getScopeOptions(derivate),
    getSummary(scope),
    getRanking(scope),
  ]);
  const aspect = one(sp.aspect);
  const tone = sp.tone === "Positive" ? "Positive" : "Negative";
  const selected = ranking.rows.find((r) => r.category === aspect);
  const where = [countryName(region), scope.engine].filter(Boolean).join(" · ");
  const eu = options.countries.filter((o) => EU27.has(o.value)).reduce((s, o) => s + o.n, 0);

  return (
    <>
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-4xl font-semibold tracking-tight">{car.derivate}</h1>
          <div className="mt-1 flex items-center gap-2 text-muted-foreground">
            <span>{car.name}</span>
            {car.engines.map((e) => (
              <Badge key={e} variant="secondary">
                {e}
              </Badge>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap gap-3">
          <ScopeSelect
            param="region"
            label="Region"
            allLabel={`World (${int(car.feedback)})`}
            options={[...(eu ? [{ value: "EU", n: eu }] : []), ...options.countries].map((o) => ({
              value: o.value,
              label: `${countryName(o.value)} (${int(o.n)})`,
            }))}
          />
          <ScopeSelect
            param="engine"
            label="Engine"
            allLabel="All engines"
            options={options.engines.map((o) => ({
              value: o.value,
              label: `${o.value} (${int(o.n)})`,
            }))}
          />
        </div>
      </header>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Feedback" value={int(summary.feedback)} hint={where} />
        <Kpi
          label="Net sentiment"
          value={mood(summary.net).label}
          valueClass={mood(summary.net).className}
          sub={signed(summary.net)}
        />
        <Kpi
          label="Feedback with a problem"
          value={summary.feedback ? pct(summary.negative / summary.feedback) : "–"}
          hint={`${int(summary.negative)} feedback with a negative aspect`}
        />
        <Kpi
          label="#1 priority"
          value={ranking.rows[0]?.category ?? "–"}
          hint={ranking.rows[0] ? `${pct(ranking.rows[0].reach)} report a problem` : undefined}
          small
        />
      </div>

      <PriorityTable ranking={ranking} sp={sp} />
      <Strengths ranking={ranking} sp={sp} />

      <AspectSheet
        open={!!selected}
        closeHref={hrefWith(sp, { aspect: null, tone: null, n: null })}
      >
        {selected && (
          <Suspense fallback={<Skeleton className="m-6 h-64" />}>
            <AspectDetail
              scope={scope}
              where={`${car.derivate} · ${where}`}
              ranking={ranking}
              row={selected}
              tone={tone}
              limit={Math.min(Math.max(Number(sp.n) || 5, 5), 100)}
              sp={sp}
            />
          </Suspense>
        )}
      </AspectSheet>
    </>
  );
}

function PriorityTable({ ranking, sp }: { ranking: Ranking; sp: Search }) {
  const max = ranking.rows[0]?.priority || 1;
  return (
    <Card>
      <CardHeader>
        <CardTitle>What to improve first</CardTitle>
        <CardDescription>
          Priority = negative reach × severity. Reach is the share of feedback with at least one
          negative aspect in the category; severity is the mean intensity of those aspects. Demand
          counts feature requests separately. Click a row for the reasoning and verbatims.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8">#</TableHead>
              <TableHead>Category</TableHead>
              <TableHead className="w-40">Priority</TableHead>
              <TableHead className="text-right">Reach</TableHead>
              <TableHead className="text-right">Severity</TableHead>
              <TableHead className="text-right">Demand</TableHead>
              <TableHead className="text-right">Net</TableHead>
              <TableHead>Top issue</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {ranking.rows.map((r, i) => (
              <TableRow key={r.category} className="relative">
                <TableCell className="text-muted-foreground tabular-nums">{i + 1}</TableCell>
                <TableCell className="font-medium">
                  <Link
                    href={hrefWith(sp, { aspect: r.category, tone: null, n: null })}
                    scroll={false}
                    prefetch={false}
                    className="after:absolute after:inset-0 hover:underline"
                  >
                    {r.category}
                  </Link>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <Bar value={r.priority / max} className="bg-destructive" />
                    <span className="w-8 text-right text-xs tabular-nums">
                      {(r.priority * 100).toFixed(1)}
                    </span>
                  </div>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {pct(r.reach)}{" "}
                  <span className="text-xs text-muted-foreground">({int(r.negative)})</span>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {r.negative ? r.severity.toFixed(2) : "–"}
                </TableCell>
                <TableCell className="text-right tabular-nums">{int(r.demand)}</TableCell>
                <TableCell className={cn("text-right tabular-nums", signTone(r.net))}>
                  {signed(r.net)}
                </TableCell>
                <TableCell className="text-muted-foreground">{r.topIssue ?? "–"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <p className="mt-3 text-xs text-muted-foreground">
          {int(ranking.total)} feedback in scope. {int(ranking.unclassified)} feedback with
          unclassified aspects are not ranked.
        </p>
      </CardContent>
    </Card>
  );
}

function Strengths({ ranking, sp }: { ranking: Ranking; sp: Search }) {
  const top = ranking.rows
    .filter((r) => r.positive)
    .sort((a, b) => b.positive - a.positive)
    .slice(0, 3);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Strengths to keep</CardTitle>
        <CardDescription>Categories praised by the most feedback.</CardDescription>
      </CardHeader>
      <CardContent>
        <ol className="grid gap-4 sm:grid-cols-3">
          {top.map((r) => (
            <li key={r.category}>
              <Link
                href={hrefWith(sp, { aspect: r.category, tone: "Positive", n: null })}
                scroll={false}
                prefetch={false}
                className="flex flex-col gap-1 rounded-md hover:underline"
              >
                <span className="text-sm font-medium">{r.category}</span>
                <div className="flex items-center gap-2">
                  <Bar
                    value={ranking.total ? r.positive / ranking.total : 0}
                    className="bg-emerald-500"
                  />
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {ranking.total ? pct(r.positive / ranking.total) : "–"}
                  </span>
                </div>
              </Link>
            </li>
          ))}
          {!top.length && <li className="text-sm text-muted-foreground">No praise in scope.</li>}
        </ol>
      </CardContent>
    </Card>
  );
}
