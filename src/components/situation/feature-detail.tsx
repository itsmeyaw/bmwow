import { SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { int, pct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { getFeatureDetail, type Finding, type Signal } from "@/server/situation/queries";
import {
  AssessmentBadge,
  Cited,
  DIRECTION_LABEL,
  INTENTS,
  Section,
  ShareBar,
  Stat,
  num,
  sentence,
  target,
} from "./parts";

const OPTION_LABEL: Record<string, string> = {
  ours: "Today (ours)",
  competitor_median: "Competitor median",
  best_in_class: "Best in class",
};

const SOURCE_TYPE: Record<string, string> = {
  product_catalog: "BMW price list",
  customer_study: "customer study",
  sales_dataset: "sales data",
  web_page: "web page",
  ontology: "competitor data",
  model_record: "model record",
};

/** A stored record excerpt ("A: x = 1 (statement; key=value; …)") as its readable statement. */
function readable(excerpt: string) {
  const m = excerpt.match(/\((.+?)[;)]/);
  return m ? m[1] : excerpt;
}

const BASELINE_STATUS: Record<string, string> = {
  known_present: "Present today",
  known_absent: "Not offered today",
  unknown: "Unknown",
};

/** The full analysis of one feature in one run, as shown in the side sheet. */
export async function FeatureDetailView({
  runId,
  attribute,
  where,
}: {
  runId: string;
  attribute: string;
  where: string;
}) {
  const d = await getFeatureDetail(runId, attribute);
  if (!d) return <p className="p-6 text-sm text-muted-foreground">Feature not found.</p>;
  const { feature: f, requirement: r } = d;
  const maxShare = Math.max(0.05, ...d.signals.map((s) => s.ciHigh));
  const study = d.ours.filter((o) => o.claim.includes("study") || o.unit === "share");
  const catalog = d.ours.filter((o) => !study.includes(o));

  return (
    <>
      <SheetHeader className="border-b p-6">
        <div className="flex flex-wrap items-center gap-2">
          <SheetTitle className="text-xl">{sentence(f.label)}</SheetTitle>
          <AssessmentBadge value={f.assessment} method={f.method} />
          {r && <span className="font-mono text-xs text-muted-foreground">{r.reqId}</span>}
        </div>
        <SheetDescription>
          {where} · {f.area.replaceAll("_", " ")} · importance rank #{f.rank}
        </SheetDescription>
      </SheetHeader>

      <div className="flex flex-col gap-8 p-6">
        {r && (
          <Section title="Requirement">
            <div className="rounded-lg border p-4">
              <p className="text-sm leading-relaxed">
                <span className="font-medium">{INTENTS[r.changeIntent]}: </span>
                {r.statement}
              </p>
              <dl className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
                <Stat
                  label="Target"
                  value={
                    target(r.targetOperator, r.targetValue, r.targetUnit, r.targetCondition) ??
                    "set by PM"
                  }
                />
                <Stat label="Why this target" value={r.targetRule ?? "–"} />
                <Stat label="Current model" value={BASELINE_STATUS[r.baselineStatus] ?? "–"} />
              </dl>
              {r.options.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2 text-xs">
                  {r.options.map((o) => (
                    <span key={o.label} className="rounded-md bg-muted px-2 py-1 tabular-nums">
                      {OPTION_LABEL[o.label] ?? o.label}: {num(o.value)} {o.unit}
                    </span>
                  ))}
                </div>
              )}
              {r.customerValue && (
                <p className="mt-3 text-sm text-muted-foreground">{r.customerValue}</p>
              )}
              {r.acceptance && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Acceptance: {r.acceptance.description} · verified by{" "}
                  {r.acceptance.verification_method.replaceAll("_", " ")}
                </p>
              )}
              {r.openPoints.length > 0 && (
                <ul className="mt-2 list-disc pl-5 text-xs text-amber-700 dark:text-amber-300">
                  {r.openPoints.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              )}
            </div>
          </Section>
        )}

        <Section
          title="Why"
          hint={
            f.method === "judge"
              ? `Judged by the LLM with a fixed rubric; checked by code rules (${f.guardStatus}). Code suggested: ${f.ruleSuggestion}.`
              : "Rule-based: computed by code from the shares and comparisons (low certainty)."
          }
        >
          {f.whatExactly && <p className="text-sm font-medium">{f.whatExactly}</p>}
          {f.reasoning && <Cited text={f.reasoning} />}
          <dl className="grid grid-cols-3 gap-2 text-sm">
            <Stat label="Certainty" value={f.certainty ?? "–"} />
            <Stat label="Widespread" value={f.widespread ?? "–"} />
            <Stat
              label="Problem share"
              value={f.problemShare != null ? pct(f.problemShare) : "–"}
            />
          </dl>
          {f.facts.length > 0 && (
            <ul className="list-disc pl-5 text-sm text-muted-foreground">
              {f.facts.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          )}
        </Section>

        <Section
          title="Customers"
          hint="Share of feedback items, with the 95% interval as a box. Thin = small sample."
          empty={!d.signals.length && "No customer feedback on this feature."}
        >
          <Signals signals={d.signals} max={maxShare} />
        </Section>

        {d.subThemes.length > 0 && (
          <Section title="What exactly customers mean">
            <ul className="flex flex-col gap-1 text-sm">
              {d.subThemes.map((t) => (
                <li key={`${t.direction}-${t.name}`} className="flex justify-between gap-3">
                  <span>
                    <span className="text-xs text-muted-foreground">
                      {DIRECTION_LABEL[t.direction]} ·{" "}
                    </span>
                    {t.name}
                  </span>
                  <span className="text-xs whitespace-nowrap text-muted-foreground tabular-nums">
                    {int(t.k)} of {int(t.ofTotal)}
                  </span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        <Section
          title="Customer feedback"
          hint="Verbatim, alternating problem / request / praise so counter-evidence is shown."
          empty={!d.quotes.length && "No feedback examples."}
        >
          {d.quotes.map((q) => (
            <figure key={q.sourceId} className="rounded-lg border p-3 text-sm">
              <blockquote className="leading-relaxed">{q.text}</blockquote>
              <figcaption className="mt-2 text-xs text-muted-foreground">
                {q.direction ? DIRECTION_LABEL[q.direction] : "–"} ·{" "}
                <span className="font-mono">{q.sourceId.replace("fb:", "")}</span>
              </figcaption>
            </figure>
          ))}
        </Section>

        <Section
          title="Competitors"
          hint="Only like-for-like values are compared: same unit, test standard and powertrain."
          empty={
            !d.competitorValues.length &&
            !d.competitorFacts.length &&
            "No competitor evidence for this feature."
          }
        >
          {d.competitorValues.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Basis</TableHead>
                  <TableHead className="text-right">n</TableHead>
                  <TableHead className="text-right">Min</TableHead>
                  <TableHead className="text-right">Median</TableHead>
                  <TableHead className="text-right">Max</TableHead>
                  <TableHead className="text-right">Ours</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {d.competitorValues.map((v, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-xs">
                      {v.unit} · {v.condition || "–"}
                      {v.lowerIsBetter && (
                        <span className="text-muted-foreground"> · lower is better</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{v.n}</TableCell>
                    <TableCell className="text-right tabular-nums">{num(v.minimum)}</TableCell>
                    <TableCell className="text-right font-medium tabular-nums">
                      {num(v.median)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{num(v.maximum)}</TableCell>
                    <TableCell
                      className={cn(
                        "text-right tabular-nums",
                        v.oursRank === 1 && "text-emerald-600 dark:text-emerald-400",
                      )}
                    >
                      {v.ours != null ? (
                        <>
                          {num(v.ours)}{" "}
                          <span className="text-xs text-muted-foreground">
                            #{v.oursRank}/{v.fieldSize}
                          </span>
                        </>
                      ) : (
                        "–"
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          <Claims items={d.competitorFacts} limit={10} />
        </Section>

        <Section
          title="Our current model"
          hint="From the BMW price list, customer studies and sales data."
          empty={!d.ours.length && "No catalog or study evidence for this feature."}
        >
          <Claims items={catalog} limit={10} />
          {study.length > 0 && (
            <>
              <p className="text-xs font-medium text-muted-foreground">Customer studies</p>
              <Claims items={study} limit={6} />
            </>
          )}
        </Section>

        <Section title="Trends" empty={!d.trends.length && "No trend linked to this feature."}>
          <ul className="flex flex-col gap-2 text-sm">
            {d.trends.map((t) => (
              <li key={t.findingId}>
                {t.claim}
                {t.horizon && <span className="text-xs text-muted-foreground"> · {t.horizon}</span>}
              </li>
            ))}
          </ul>
        </Section>

        {f.coverage.length > 0 && (
          <Section title="Missing evidence">
            <ul className="list-disc pl-5 text-xs text-muted-foreground">
              {f.coverage.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </Section>
        )}

        <Section title="Sources" empty={!d.sources.length && "No document sources."}>
          <details className="group rounded-md border">
            <summary className="cursor-pointer px-3 py-2 text-sm text-muted-foreground select-none">
              {d.sources.length} sources behind the catalog, competitor and trend findings
            </summary>
            <ul className="flex flex-col gap-2 p-3 pt-0 text-xs">
              {d.sources.map((s) => (
                <li key={s.sourceId} className="rounded-md bg-muted/40 p-2">
                  <p className="font-medium">
                    {s.url ? (
                      <a href={s.url} target="_blank" rel="noreferrer" className="hover:underline">
                        {s.title || s.url}
                      </a>
                    ) : (
                      (s.title ?? s.sourceId)
                    )}{" "}
                    <span className="font-normal text-muted-foreground">
                      · {SOURCE_TYPE[s.sourceType ?? ""] ?? s.kind}
                    </span>
                  </p>
                  <p className="mt-1 line-clamp-2 text-muted-foreground">{readable(s.excerpt)}</p>
                </li>
              ))}
            </ul>
          </details>
        </Section>
      </div>
    </>
  );
}

function Signals({ signals, max }: { signals: Signal[]; max: number }) {
  return (
    <div className="flex flex-col gap-2">
      {signals.map((s) => (
        <div
          key={s.findingId}
          className="grid grid-cols-[7rem_1fr_9rem] items-center gap-3 text-sm"
        >
          <span>
            {DIRECTION_LABEL[s.direction]}
            <span className="text-xs text-muted-foreground"> · {s.region ?? "all"}</span>
          </span>
          <ShareBar
            share={s.share}
            ciLow={s.ciLow}
            ciHigh={s.ciHigh}
            direction={s.direction}
            max={max}
          />
          <span className="text-right text-xs tabular-nums">
            <span className="font-medium">{pct(s.share)}</span>{" "}
            <span className="text-muted-foreground">
              ({int(s.k)} of {int(s.n)}){s.thin && " · thin"}
            </span>
          </span>
        </div>
      ))}
    </div>
  );
}

/** Drops a stored record's technical tail ("…; availability=…; metric=…)") from a claim. */
const plainClaim = (claim: string) => claim.replace(/;\s*[a-z_]+=[\s\S]*\)(\.?)$/, ")$1");

function Claims({ items, limit }: { items: Finding[]; limit: number }) {
  if (!items.length) return null;
  return (
    <ul className="flex flex-col gap-1.5 text-sm">
      {items.slice(0, limit).map((o) => (
        <li key={o.findingId} className="leading-snug">
          {plainClaim(o.claim)}
        </li>
      ))}
      {items.length > limit && (
        <li className="text-xs text-muted-foreground">+{items.length - limit} more</li>
      )}
    </ul>
  );
}
