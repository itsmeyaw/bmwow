import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { AspectSheet, ScopeSelect } from "@/components/car-controls";
import { VerbatimActions } from "@/components/chat-context";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
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
import { cn } from "@/lib/utils";
import {
  getCategoryDetail,
  getEvidence,
  getRanking,
  getScopeOptions,
  getSummary,
  listCars,
  type CategoryRow,
  type Evidence,
  type Ranking,
  type Scope,
} from "@/server/analysis/queries";

type Search = Record<string, string | string[] | undefined>;
const one = (v: string | string[] | undefined) => (typeof v === "string" && v ? v : null);

/** Same page, with some search params changed (`null` removes one). */
function hrefWith(sp: Search, patch: Record<string, string | number | null>) {
  const next = new URLSearchParams();
  for (const [k, v] of Object.entries(sp)) if (typeof v === "string") next.set(k, v);
  for (const [k, v] of Object.entries(patch)) {
    if (v == null) next.delete(k);
    else next.set(k, String(v));
  }
  return `?${next}`;
}

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
  const scope: Scope = { derivate, country: one(sp.region), engine: one(sp.engine) };
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
  const where = [countryName(scope.country), scope.engine].filter(Boolean).join(" · ");

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
            options={options.countries.map((o) => ({
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

function Kpi({
  label,
  value,
  hint,
  small,
  sub,
  valueClass,
}: {
  label: string;
  value: string;
  hint?: string;
  small?: boolean;
  /** Secondary figure shown small below the value. */
  sub?: string;
  valueClass?: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardTitle className={`flex flex-col gap-1 ${small ? "text-lg" : "text-3xl tabular-nums"}`}>
          <span className={`${small ? "" : "whitespace-nowrap"} ${valueClass ?? ""}`}>{value}</span>
          {sub && (
            <span className="text-sm font-normal text-muted-foreground tabular-nums">{sub}</span>
          )}
        </CardTitle>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </CardHeader>
    </Card>
  );
}

function Bar({ value, className }: { value: number; className: string }) {
  return (
    <div className="h-2 w-full min-w-16 rounded-full bg-muted">
      <div
        className={`h-2 rounded-full ${className}`}
        style={{ width: `${Math.min(value, 1) * 100}%` }}
      />
    </div>
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

async function AspectDetail({
  scope,
  where,
  ranking,
  row,
  tone,
  limit,
  sp,
}: {
  scope: Scope;
  where: string;
  ranking: Ranking;
  row: CategoryRow;
  tone: "Negative" | "Positive";
  limit: number;
  sp: Search;
}) {
  const [{ issues, terms }, evidence] = await Promise.all([
    getCategoryDetail(scope, row.category),
    getEvidence(scope, row.category, tone, limit + 1),
  ]);
  const rank = ranking.rows.indexOf(row) + 1;
  const negIssues = issues.filter((x) => x.sentiment === "Negative");
  const negTotal = negIssues.reduce((n, x) => n + x.n, 0);
  const top = negIssues[0];
  const maxIssue = Math.max(1, ...issues.map((x) => x.n));
  const negative = tone === "Negative";

  return (
    <>
      <SheetHeader className="border-b p-6">
        <SheetTitle className="text-xl">{row.category}</SheetTitle>
        <SheetDescription>{where}</SheetDescription>
      </SheetHeader>
      <div className="flex flex-col gap-6 p-6">
        <section className="flex flex-col gap-3">
          <h3 className="text-sm font-medium">
            Why it ranks #{rank} of {ranking.rows.length}
          </h3>
          <p className="text-sm leading-relaxed">
            {pct(row.reach)} of feedback in scope reports a problem with {row.category} (
            {int(row.negative)} of {int(ranking.total)}), with a mean severity of{" "}
            {row.severity.toFixed(2)}.
            {top && (
              <>
                {" "}
                The most common issue is <strong>{top.issue}</strong> ({pct(top.n / negTotal)} of
                negative mentions).
              </>
            )}{" "}
            {int(row.positive)} feedback praise it and {int(row.demand)} ask for something new.
          </p>
          <dl className="grid grid-cols-3 gap-2 text-sm sm:grid-cols-5">
            <Stat label="Priority" value={(row.priority * 100).toFixed(1)} />
            <Stat label="Reach" value={pct(row.reach)} />
            <Stat label="Severity" value={row.negative ? row.severity.toFixed(2) : "–"} />
            <Stat label="Demand" value={int(row.demand)} />
            <Stat label="Net" value={signed(row.net)} />
          </dl>
        </section>

        <section className="flex flex-col gap-2">
          <h3 className="text-sm font-medium">Issue types</h3>
          {issues.map((x) => (
            <div
              key={`${x.issue}-${x.sentiment}`}
              className="grid grid-cols-[12rem_1fr_3rem] items-center gap-2 text-sm"
            >
              <span className="truncate">{x.issue}</span>
              <Bar
                value={x.n / maxIssue}
                className={
                  x.sentiment === "Negative"
                    ? "bg-destructive"
                    : x.sentiment === "Positive"
                      ? "bg-emerald-500"
                      : "bg-sky-500"
                }
              />
              <span className="text-right text-xs tabular-nums text-muted-foreground">
                {int(x.n)}
              </span>
            </div>
          ))}
        </section>

        <section className="flex flex-col gap-2">
          <h3 className="text-sm font-medium">Aspects mentioned</h3>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Aspect</TableHead>
                <TableHead className="text-right">Negative</TableHead>
                <TableHead className="text-right">Positive</TableHead>
                <TableHead className="text-right">Requests</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {terms.map((t) => (
                <TableRow key={t.term}>
                  <TableCell>{t.term}</TableCell>
                  <TableCell className="text-right tabular-nums">{int(t.negative)}</TableCell>
                  <TableCell className="text-right tabular-nums">{int(t.positive)}</TableCell>
                  <TableCell className="text-right tabular-nums">{int(t.demand)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>

        <section className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium">
              {negative ? "Evidence: complaints" : "Evidence: praise"}
            </h3>
            <Link
              href={hrefWith(sp, { tone: negative ? "Positive" : null, n: null })}
              scroll={false}
              prefetch={false}
              className="text-xs text-muted-foreground hover:underline"
            >
              Show {negative ? "praise" : "complaints"} instead
            </Link>
          </div>
          {evidence.slice(0, limit).map((e) => (
            <Verbatim
              key={e.id}
              e={e}
              actions={
                <VerbatimActions
                  card={{ ...e, category: row.category, tone }}
                  closeHref={hrefWith(sp, { aspect: null, tone: null, n: null })}
                />
              }
            />
          ))}
          {!evidence.length && <p className="text-sm text-muted-foreground">No verbatims.</p>}
          {evidence.length > limit && (
            <Link
              href={hrefWith(sp, { n: limit + 10 })}
              scroll={false}
              prefetch={false}
              className="self-start text-sm font-medium hover:underline"
            >
              Load more
            </Link>
          )}
        </section>
      </div>
    </>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-muted/50 p-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-medium tabular-nums">{value}</dd>
    </div>
  );
}

function Verbatim({ e, actions }: { e: Evidence; actions: React.ReactNode }) {
  const at = e.quote ? e.text.toLowerCase().indexOf(e.quote.toLowerCase()) : -1;
  return (
    <figure className="rounded-lg border p-3 text-sm">
      <blockquote className="leading-relaxed whitespace-pre-line">
        {at < 0 ? (
          e.text
        ) : (
          <>
            {e.text.slice(0, at)}
            <mark className="rounded bg-yellow-200/70 px-0.5 dark:bg-yellow-500/30 dark:text-inherit">
              {e.text.slice(at, at + e.quote!.length)}
            </mark>
            {e.text.slice(at + e.quote!.length)}
          </>
        )}
      </blockquote>
      {at < 0 && e.quote && (
        <p className="mt-2 text-xs text-muted-foreground">Quote: “{e.quote}”</p>
      )}
      <figcaption className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="font-mono">{e.id}</span>
        <span>{countryName(e.country)}</span>
        {e.engine && <span>{e.engine}</span>}
        {e.source && <span>{e.source}</span>}
        <span>
          {e.term} · {e.issue} · intensity {e.score.toFixed(2)}
        </span>
        {actions}
      </figcaption>
    </figure>
  );
}
