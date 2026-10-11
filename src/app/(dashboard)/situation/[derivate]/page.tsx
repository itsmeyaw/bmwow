import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";
import { AspectSheet } from "@/components/car-controls";
import { FeatureDetailView } from "@/components/situation/feature-detail";
import {
  ASSESSMENTS,
  AssessmentBadge,
  INTENTS,
  sentence,
  target,
} from "@/components/situation/parts";
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
import { CATEGORIES, categoryLabel, categoryOf } from "@/lib/feature-category";
import { int, pct } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  getRun,
  listFeatures,
  listRuns,
  type FeatureRow,
  type Run,
} from "@/server/situation/queries";

/** "ALL" reads as "All regions"; single regions keep their code. */
const regionLabel = (region: string) => (region === "ALL" ? "All" : region);

type Search = Record<string, string | string[] | undefined>;
const one = (v: string | string[] | undefined) => (typeof v === "string" && v ? v : null);

function hrefWith(sp: Search, patch: Record<string, string | null>) {
  const next = new URLSearchParams();
  for (const [k, v] of Object.entries(sp)) if (typeof v === "string") next.set(k, v);
  for (const [k, v] of Object.entries(patch)) {
    if (v == null) next.delete(k);
    else next.set(k, v);
  }
  return `?${next}`;
}

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
  const features = await listFeatures(run.runId);
  const category = CATEGORIES.find((c) => c.key === one(sp.category))?.key ?? null;
  const inCategory = (f: FeatureRow) => !category || categoryOf(f.attribute, f.area) === category;
  const allRecommended = features.filter((f) => f.reqId);
  const recommended = allRecommended.filter(inCategory);
  const assessed = features.filter(
    (f) =>
      !f.reqId && f.assessment !== "unclear" && f.assessment !== "not_assessed" && inCategory(f),
  );
  const scoped = features.filter(inCategory); // key figures follow the category filter
  const unclear = scoped.length - recommended.length - assessed.length;
  const counts = Map.groupBy(scoped, (f) => f.assessment);
  const selected = features.find((f) => f.attribute === one(sp.feature));

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
        <nav className="flex flex-col gap-1 text-xs text-muted-foreground">
          Region
          <div className="flex gap-1">
            {regions.map((r) => (
              <Link
                key={r.region}
                href={hrefWith(sp, { region: r.region, feature: null })}
                scroll={false}
                className={cn(
                  "rounded-md border px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-muted",
                  r.region === region &&
                    "border-primary bg-primary text-primary-foreground hover:bg-primary/90",
                )}
              >
                {regionLabel(r.region)}
              </Link>
            ))}
          </div>
        </nav>
      </header>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi
          label="Recommended requirements"
          value={int(recommended.length)}
          hint="Judged by the rubric, checked by code rules"
        />
        <Kpi
          label="Gaps · demands"
          value={`${int(counts.get("gap")?.length ?? 0)} · ${int(counts.get("demand")?.length ?? 0)}`}
          hint={`${int(counts.get("hygiene_factor")?.length ?? 0)} hygiene factors, ${int(counts.get("strength")?.length ?? 0)} strengths`}
        />
        <Kpi
          label="Features analysed"
          value={int(scoped.length)}
          hint={`${int(unclear)} with too little evidence to decide`}
        />
        <DataCoverage run={run} />
      </div>

      <CategoryFilter features={allRecommended} active={category} sp={sp} />
      <RequirementsTable
        rows={recommended}
        sp={sp}
        emptyReason={
          category && allRecommended.length
            ? `No requirement in ${categoryLabel(category)} for this run.`
            : emptyReason(run, features)
        }
      />
      {assessed.length > 0 && <OtherFeatures rows={assessed} unclear={unclear} sp={sp} />}
      <Legend />

      <AspectSheet open={!!selected} closeHref={hrefWith(sp, { feature: null })}>
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
      <p className="text-xs text-muted-foreground">
        Run {run.runId} · {new Date(run.createdAt).toLocaleString("en")}
        {run.llmModel && ` · ${run.llmModel}`}
      </p>
    </>
  );
}

/** One button per category with its requirement count; the choice lives in the URL. */
function CategoryFilter({
  features,
  active,
  sp,
}: {
  features: FeatureRow[];
  active: string | null;
  sp: Search;
}) {
  const counts = Map.groupBy(features, (f) => categoryOf(f.attribute, f.area));
  const items = [
    { key: null, label: "All categories", n: features.length },
    ...CATEGORIES.map((c) => ({ key: c.key, label: c.label, n: counts.get(c.key)?.length ?? 0 })),
  ].filter((c) => c.key === null || c.n > 0 || c.key === active);
  return (
    <nav className="flex flex-wrap items-center gap-2" aria-label="Filter by category">
      <span className="text-xs text-muted-foreground">Category</span>
      {items.map((c) => (
        <Link
          key={c.key ?? "all"}
          href={hrefWith(sp, { category: c.key, feature: null })}
          scroll={false}
          className={cn(
            "rounded-full border px-3 py-1 text-sm transition-colors hover:bg-muted",
            c.key === active &&
              "border-primary bg-primary text-primary-foreground hover:bg-primary/90",
          )}
        >
          {c.label} <span className="tabular-nums opacity-70">{c.n}</span>
        </Link>
      ))}
    </nav>
  );
}

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card>
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-3xl tabular-nums">{value}</CardTitle>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </CardHeader>
    </Card>
  );
}

const AGENTS = [
  ["baseline", "Our model"],
  ["competition", "Competitors"],
  ["feedback", "Customers"],
  ["trends", "Trends"],
] as const;

function DataCoverage({ run }: { run: Run }) {
  return (
    <Card>
      <CardHeader>
        <CardDescription>Evidence views</CardDescription>
        <div className="flex flex-wrap gap-1 pt-1">
          {AGENTS.map(([key, label]) => {
            const s = run.agentStatus?.[key];
            const tone =
              s?.status === "ok"
                ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                : s?.status === "partial"
                  ? "bg-amber-500/10 text-amber-700 dark:text-amber-300"
                  : "bg-destructive/10 text-destructive";
            return (
              <Badge
                key={key}
                variant="secondary"
                className={tone}
                title={[...(s?.unavailable ?? []), ...(s?.errors ?? [])].join("\n") || "ok"}
              >
                {label}: {s?.status ?? "missing"}
              </Badge>
            );
          })}
        </div>
        <p className="text-xs text-muted-foreground">Hover a view for what was missing.</p>
      </CardHeader>
    </Card>
  );
}

function FeatureLink({ f, sp }: { f: FeatureRow; sp: Search }) {
  return (
    <Link
      href={hrefWith(sp, { feature: f.attribute })}
      scroll={false}
      prefetch={false}
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
  return (
    <Card>
      <CardHeader>
        <CardTitle>Recommended requirements</CardTitle>
        <CardDescription>
          In order of customer impact. Targets come from like-for-like competitor comparisons (same
          unit, test standard and powertrain) or today's value. Click a feature for the full
          analysis behind it.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-16">#</TableHead>
              <TableHead>Feature</TableHead>
              <TableHead>Category</TableHead>
              <TableHead>Assessment</TableHead>
              <TableHead className="min-w-48">Requirement</TableHead>
              <TableHead>Target</TableHead>
              <TableHead className="text-right">Problems</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((f) => (
              <TableRow key={f.attribute} className="relative align-top">
                <TableCell className="font-mono text-xs text-muted-foreground">{f.reqId}</TableCell>
                <TableCell>
                  <FeatureLink f={f} sp={sp} />
                  {!f.isMapped && <p className="text-xs text-muted-foreground">feedback area</p>}
                </TableCell>
                <TableCell className="text-sm whitespace-nowrap text-muted-foreground">
                  {categoryLabel(categoryOf(f.attribute, f.area))}
                </TableCell>
                <TableCell>
                  <AssessmentBadge value={f.assessment} method={f.method} />
                </TableCell>
                <TableCell className="text-sm whitespace-normal">
                  {f.changeIntent && (
                    <span className="mr-1 font-medium">{INTENTS[f.changeIntent]}:</span>
                  )}
                  <span className="text-muted-foreground">{f.requirement}</span>
                </TableCell>
                <TableCell className="text-sm tabular-nums">
                  {f.targetValue != null ? (
                    <>
                      <span className="font-medium whitespace-nowrap">
                        {target(f.targetOperator, f.targetValue, f.targetUnit, null)}
                      </span>
                      {f.targetCondition && (
                        <p className="text-xs text-muted-foreground">{f.targetCondition}</p>
                      )}
                    </>
                  ) : (
                    <span className="text-xs text-muted-foreground">set by PM</span>
                  )}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {f.problemShare != null ? pct(f.problemShare) : "–"}
                </TableCell>
              </TableRow>
            ))}
            {!rows.length && (
              <TableRow>
                <TableCell colSpan={7} className="whitespace-normal text-muted-foreground">
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

function OtherFeatures({ rows, unclear, sp }: { rows: FeatureRow[]; unclear: number; sp: Search }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Other assessed features</CardTitle>
        <CardDescription>
          Assessed but not recommended: mostly rule-based (computed from the numbers, low
          certainty). {int(unclear)} further features had too little evidence to decide.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Feature</TableHead>
              <TableHead>Category</TableHead>
              <TableHead>Assessment</TableHead>
              <TableHead className="text-right">Problem share</TableHead>
              <TableHead className="text-right">Competitor comparisons</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((f) => (
              <TableRow key={f.attribute} className="relative">
                <TableCell>
                  <FeatureLink f={f} sp={sp} />
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {categoryLabel(categoryOf(f.attribute, f.area))}
                </TableCell>
                <TableCell>
                  <AssessmentBadge value={f.assessment} method={f.method} />
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {f.problemShare != null ? pct(f.problemShare) : "–"}
                </TableCell>
                <TableCell className="text-right tabular-nums">{f.competitorComparisons}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function Legend() {
  return (
    <dl className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2 xl:grid-cols-4">
      {(["gap", "demand", "hygiene_factor", "strength"] as const).map((k) => (
        <div key={k} className="flex flex-col gap-1">
          <dt>
            <AssessmentBadge value={k} />
          </dt>
          <dd>{ASSESSMENTS[k].hint}</dd>
        </div>
      ))}
    </dl>
  );
}
