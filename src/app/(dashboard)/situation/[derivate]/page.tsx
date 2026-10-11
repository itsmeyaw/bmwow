import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";
import { AspectSheet, ScopeSelect } from "@/components/car-controls";
import { AspectDetail, Bar, hrefWith, Kpi, one, type Search } from "@/components/feedback";
import {
  CategoryChart,
  VerdictDonut,
  VoiceChart,
  type CategoryBar,
  type VoiceRow,
} from "@/components/situation/charts";
import { FeatureDetailView } from "@/components/situation/feature-detail";
import {
  AssessmentBadge,
  plainRequirement,
  sentence,
  target,
  unjargon,
  VERDICTS,
} from "@/components/situation/parts";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CATEGORIES, categoryLabel, categoryOf } from "@/lib/feature-category";
import { int, mood, pct, signed } from "@/lib/format";
import { marketCountries } from "@/lib/markets";
import { cn } from "@/lib/utils";
import {
  getRanking,
  getScopeOptions,
  getSummary,
  type Ranking,
  type Scope,
} from "@/server/analysis/queries";
import {
  getRun,
  listFeatures,
  listRuns,
  type FeatureRow,
  type Run,
} from "@/server/situation/queries";

/** "ALL" reads as "All regions"; single regions keep their code. */
const regionLabel = (region: string) => (region === "ALL" ? "All" : region);

/** Params that open a side sheet; changing the market or a filter closes them. */
const CLOSED = { feature: null, aspect: null, tone: null, n: null };

export default function SituationCarPage(props: PageProps<"/situation/[derivate]">) {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full rounded-xl" />}>
      <CarView {...props} />
    </Suspense>
  );
}

async function CarView({ params, searchParams }: PageProps<"/situation/[derivate]">) {
  await connection();
  const { derivate } = await params;
  const sp: Search = await searchParams;
  const regions = (await listRuns()).filter((r) => r.modelCode === derivate);
  if (!regions.length) notFound();
  const region = one(sp.region) ?? regions[0].region;
  const run = await getRun(derivate, region);
  if (!run) notFound();
  const scope: Scope = {
    derivate,
    country: null,
    engine: one(sp.engine),
    countries: marketCountries(run.region),
  };
  const [features, options, summary, ranking] = await Promise.all([
    listFeatures(run.runId),
    getScopeOptions(derivate),
    getSummary(scope),
    getRanking(scope),
  ]);

  const category = CATEGORIES.find((c) => c.key === one(sp.category))?.key ?? null;
  const inCategory = (f: FeatureRow) => !category || categoryOf(f.attribute, f.area) === category;
  const allRecommended = features.filter((f) => f.reqId);
  const recommended = allRecommended.filter(inCategory);
  const scoped = features.filter(inCategory); // key figures follow the category filter
  const assessed = scoped.filter((f) => !f.reqId && isDecided(f));
  const unclear = scoped.length - recommended.length - assessed.length;
  const counts = Object.fromEntries(
    [...Map.groupBy(scoped, (f) => (isDecided(f) ? f.assessment : "unclear"))].map(([k, v]) => [
      k,
      v.length,
    ]),
  );

  const selected = features.find((f) => f.attribute === one(sp.feature));
  const aspect = selected ? undefined : ranking.rows.find((r) => r.category === one(sp.aspect));
  const tone = sp.tone === "Positive" ? "Positive" : "Negative";
  const where = [run.modelCode, regionLabel(run.region), scope.engine].filter(Boolean).join(" · ");
  const top = ranking.rows[0];
  const m = mood(summary.net);

  return (
    <>
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-4xl font-semibold tracking-tight">{run.modelCode}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-muted-foreground">
            <span>{run.modelName}</span>
            {run.segment && <Badge variant="secondary">{run.segment.replaceAll("_", " ")}</Badge>}
          </div>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <nav className="flex flex-col gap-1 text-xs text-muted-foreground">
            Market
            <div className="flex gap-1">
              {regions.map((r) => (
                <Link
                  key={r.region}
                  href={hrefWith(sp, { region: r.region, ...CLOSED })}
                  scroll={false}
                  className={cn(
                    "rounded-md border px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-muted",
                    r.region === run.region &&
                      "border-primary bg-primary text-primary-foreground hover:bg-primary/90",
                  )}
                >
                  {regionLabel(r.region)}
                </Link>
              ))}
            </div>
          </nav>
          {options.engines.length > 0 && (
            <ScopeSelect
              param="engine"
              label="Feedback engine"
              allLabel="All engines"
              options={options.engines.map((o) => ({ value: o.value, label: o.value }))}
            />
          )}
        </div>
      </header>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi
          label="Customer feedback"
          value={summary.feedback ? int(summary.feedback) : "–"}
          hint={
            summary.feedback ? (
              <>
                <span className={cn("font-medium", m.className)}>{m.label}</span> sentiment ·{" "}
                {signed(summary.net)}
              </>
            ) : (
              "None in this market"
            )
          }
        />
        <Kpi
          label="Feedback with a problem"
          value={summary.feedback ? pct(summary.negative / summary.feedback) : "–"}
          hint={
            top && (
              <>
                Top: <span className="font-medium text-foreground">{top.category}</span>
              </>
            )
          }
        />
        <Kpi
          label="Recommended requirements"
          value={int(recommended.length)}
          hint={`from ${int(scoped.length)} features analysed`}
        />
        <EvidenceKpi run={run} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Feature verdicts</CardTitle>
            <CardDescription>
              {category ? categoryLabel(category) : "All categories"} · hover for meaning
            </CardDescription>
          </CardHeader>
          <CardContent>
            <VerdictDonut counts={counts} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Requirements by category</CardTitle>
            <CardDescription>Click a bar to filter</CardDescription>
            {category && (
              <CardAction>
                <Link
                  href={hrefWith(sp, { category: null, ...CLOSED })}
                  scroll={false}
                  className="text-sm text-muted-foreground hover:underline"
                >
                  Clear {categoryLabel(category)}
                </Link>
              </CardAction>
            )}
          </CardHeader>
          <CardContent>
            {allRecommended.length ? (
              <CategoryChart rows={categoryBars(allRecommended, category, sp)} active={category} />
            ) : (
              <p className="text-sm text-muted-foreground">{emptyReason(run, features)}</p>
            )}
          </CardContent>
        </Card>
      </div>

      <RequirementsTable
        rows={recommended}
        sp={sp}
        emptyReason={
          category && allRecommended.length
            ? `No requirement in ${categoryLabel(category)} for this run.`
            : emptyReason(run, features)
        }
      />

      <CustomerVoice ranking={ranking} sp={sp} derivate={derivate} where={where} />

      {assessed.length > 0 && <OtherFeatures rows={assessed} unclear={unclear} sp={sp} />}

      <AspectSheet open={!!selected} closeHref={hrefWith(sp, CLOSED)}>
        {selected && (
          <Suspense fallback={<Skeleton className="m-6 h-64" />}>
            <FeatureDetailView
              runId={run.runId}
              attribute={selected.attribute}
              where={`${run.modelCode} · ${regionLabel(run.region)}`}
            />
          </Suspense>
        )}
      </AspectSheet>
      <AspectSheet open={!!aspect} closeHref={hrefWith(sp, CLOSED)}>
        {aspect && (
          <Suspense fallback={<Skeleton className="m-6 h-64" />}>
            <AspectDetail
              scope={scope}
              where={where}
              ranking={ranking}
              row={aspect}
              tone={tone}
              limit={Math.min(Math.max(Number(sp.n) || 5, 5), 100)}
              sp={sp}
            />
          </Suspense>
        )}
      </AspectSheet>
      <p className="text-xs text-muted-foreground">
        Run {run.runId} · {new Date(run.createdAt).toLocaleString("en")}
        {run.llmModel && ` · ${run.llmModel}`}
      </p>
    </>
  );
}

const isDecided = (f: FeatureRow) => f.assessment !== "unclear" && f.assessment !== "not_assessed";

function categoryBars(rows: FeatureRow[], active: string | null, sp: Search): CategoryBar[] {
  const by = Map.groupBy(rows, (f) => categoryOf(f.attribute, f.area));
  return CATEGORIES.filter((c) => by.has(c.key)).map((c) => {
    const fs = by.get(c.key)!;
    return {
      key: c.key,
      label: c.label,
      href: hrefWith(sp, { category: c.key === active ? null : c.key, ...CLOSED }),
      ...(Object.fromEntries(
        VERDICTS.map((v) => [v, fs.filter((f) => f.assessment === v).length]),
      ) as Record<(typeof VERDICTS)[number], number>),
    };
  });
}

const AGENTS = [
  ["baseline", "Our model"],
  ["competition", "Competitors"],
  ["feedback", "Customers"],
  ["trends", "Trends"],
] as const;

const DOT: Record<string, string> = { ok: "bg-emerald-500", partial: "bg-amber-500" };

function EvidenceKpi({ run }: { run: Run }) {
  const views = AGENTS.map(([key, label]) => ({ label, s: run.agentStatus?.[key] }));
  const ok = views.filter((v) => v.s?.status === "ok").length;
  return (
    <Kpi label="Evidence complete" value={`${ok} of ${views.length}`}>
      <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {views.map(({ label, s }) => (
          <li
            key={label}
            className="flex items-center gap-1.5"
            title={[...(s?.unavailable ?? []), ...(s?.errors ?? [])].join("\n") || "Complete"}
          >
            <span className={cn("size-2 rounded-full", DOT[s?.status ?? ""] ?? "bg-destructive")} />
            {label}
          </li>
        ))}
      </ul>
    </Kpi>
  );
}

function FeatureLink({ f, sp }: { f: FeatureRow; sp: Search }) {
  return (
    <Link
      href={hrefWith(sp, { ...CLOSED, feature: f.attribute })}
      scroll={false}
      prefetch={false}
      title={f.requirement ? unjargon(f.requirement) : undefined}
      className="font-medium after:absolute after:inset-0 hover:underline"
    >
      {sentence(f.label)}
    </Link>
  );
}

/** Why a run recommends nothing: usually no (or too little) customer feedback in the region. */
function emptyReason(run: Run, features: FeatureRow[]) {
  const fb = run.agentStatus?.feedback;
  const missing = fb?.unavailable.find((u) => u.startsWith("feedback"));
  if (missing)
    return `No customer feedback for ${run.modelCode} in ${regionLabel(run.region)}, so no customer evidence to judge.`;
  if (!features.some((f) => f.problemShare != null))
    return `Too few customer feedback items for ${run.modelCode} in ${regionLabel(run.region)} to compute shares per feature.`;
  return "No feature had enough evidence for a recommendation in this run.";
}

function RequirementsTable({
  rows,
  sp,
  emptyReason,
}: {
  rows: FeatureRow[];
  sp: Search;
  emptyReason: string;
}) {
  const max = Math.max(0.01, ...rows.map((f) => f.problemShare ?? 0));
  return (
    <Card>
      <CardHeader>
        <CardTitle>Recommended requirements</CardTitle>
        <CardDescription>By customer impact · click a row for the evidence</CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-16">#</TableHead>
              <TableHead>Feature</TableHead>
              <TableHead>Verdict</TableHead>
              <TableHead>Requirement</TableHead>
              <TableHead>Target</TableHead>
              <TableHead className="w-36">Customer problems</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((f) => (
              <TableRow key={f.attribute} className="relative">
                <TableCell className="font-mono text-xs text-muted-foreground">{f.reqId}</TableCell>
                <TableCell>
                  <FeatureLink f={f} sp={sp} />
                  <p className="text-xs text-muted-foreground">
                    {categoryLabel(categoryOf(f.attribute, f.area))}
                  </p>
                </TableCell>
                <TableCell>
                  <AssessmentBadge value={f.assessment} method={f.method} />
                </TableCell>
                <TableCell className="w-full max-w-0">
                  <p className="truncate text-sm text-muted-foreground">
                    {f.requirement && plainRequirement(f.requirement)}
                  </p>
                </TableCell>
                <TableCell className="text-sm tabular-nums">
                  {f.targetValue != null ? (
                    <span className="font-medium">
                      {target(f.targetOperator, f.targetValue, f.targetUnit, null)}
                    </span>
                  ) : (
                    <span className="text-xs text-muted-foreground">set by PM</span>
                  )}
                </TableCell>
                <TableCell>
                  {f.problemShare != null ? (
                    <div className="flex items-center gap-2">
                      <Bar value={f.problemShare / max} className="bg-destructive" />
                      <span className="w-10 text-right text-xs tabular-nums">
                        {pct(f.problemShare)}
                      </span>
                    </div>
                  ) : (
                    <span className="text-xs text-muted-foreground">–</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
            {!rows.length && (
              <TableRow>
                <TableCell colSpan={6} className="whitespace-normal text-muted-foreground">
                  {emptyReason}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

/** Complaints and praise per VFC category, from the customer feedback in this market. */
function CustomerVoice({
  ranking,
  sp,
  derivate,
  where,
}: {
  ranking: Ranking;
  sp: Search;
  derivate: string;
  where: string;
}) {
  const praised = [...ranking.rows].sort((a, b) => b.positive - a.positive).slice(0, 3);
  const shown = new Set([...ranking.rows.slice(0, 8), ...praised]);
  const total = ranking.total || 1;
  const rows: VoiceRow[] = ranking.rows
    .filter((r) => shown.has(r))
    .map((r) => ({
      label: r.category,
      problem: -r.reach,
      praise: r.positive / total,
      problemN: r.negative,
      praiseN: r.positive,
      problemHref: hrefWith(sp, { ...CLOSED, aspect: r.category }),
      praiseHref: hrefWith(sp, { ...CLOSED, aspect: r.category, tone: "Positive" }),
    }));
  return (
    <Card>
      <CardHeader>
        <CardTitle>Customer voice</CardTitle>
        {rows.length > 0 && (
          <CardDescription>
            Share of {int(ranking.total)} feedback items ({where}) · most pressing first · click a
            bar for verbatims
          </CardDescription>
        )}
        {rows.length > 0 && (
          <CardAction>
            <Link
              href={`/analysis/${derivate}${one(sp.engine) ? `?engine=${one(sp.engine)}` : ""}`}
              className="text-sm text-muted-foreground hover:underline"
            >
              Full ranking
            </Link>
          </CardAction>
        )}
      </CardHeader>
      <CardContent>
        {rows.length ? (
          <VoiceChart rows={rows} />
        ) : (
          <p className="text-sm text-muted-foreground">No customer feedback for {where}.</p>
        )}
      </CardContent>
    </Card>
  );
}

function OtherFeatures({ rows, unclear, sp }: { rows: FeatureRow[]; unclear: number; sp: Search }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Other assessed features</CardTitle>
        <CardDescription>
          Not recommended · mostly rule-based, so less certain
          {unclear > 0 && ` · ${int(unclear)} more with too little evidence`}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {VERDICTS.map((v) => {
          const fs = rows.filter((f) => f.assessment === v);
          if (!fs.length) return null;
          return (
            <div key={v} className="grid grid-cols-[10rem_1fr] items-start gap-3">
              <span className="pt-0.5">
                <AssessmentBadge value={v} />
              </span>
              <div className="flex flex-wrap gap-2">
                {fs.map((f) => (
                  <Link
                    key={f.attribute}
                    href={hrefWith(sp, { ...CLOSED, feature: f.attribute })}
                    scroll={false}
                    prefetch={false}
                    className="rounded-full border px-2.5 py-0.5 text-sm transition-colors hover:bg-muted"
                  >
                    {sentence(f.label)}
                    {f.problemShare != null && (
                      <span className="ml-1.5 text-xs text-muted-foreground tabular-nums">
                        {pct(f.problemShare)}
                      </span>
                    )}
                  </Link>
                ))}
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
