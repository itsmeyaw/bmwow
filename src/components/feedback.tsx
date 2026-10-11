import Link from "next/link";
import { VerbatimActions } from "@/components/chat-context";
import { Stat } from "@/components/situation/parts";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { countryName, int, pct, signed } from "@/lib/format";
import {
  getCategoryDetail,
  getEvidence,
  type CategoryRow,
  type Evidence,
  type Ranking,
  type Scope,
} from "@/server/analysis/queries";

/** Customer-feedback building blocks shared by /feedback and /analysis. */

export type Search = Record<string, string | string[] | undefined>;
export const one = (v: string | string[] | undefined) => (typeof v === "string" && v ? v : null);

/** Same page, with some search params changed (`null` removes one). */
export function hrefWith(sp: Search, patch: Record<string, string | number | null>) {
  const next = new URLSearchParams();
  for (const [k, v] of Object.entries(sp)) if (typeof v === "string") next.set(k, v);
  for (const [k, v] of Object.entries(patch)) {
    if (v == null) next.delete(k);
    else next.set(k, String(v));
  }
  return `?${next}`;
}

export function Kpi({
  label,
  value,
  hint,
  small,
  sub,
  valueClass,
  children,
}: {
  label: string;
  value: string;
  hint?: React.ReactNode;
  small?: boolean;
  /** Secondary figure shown small below the value. */
  sub?: string;
  valueClass?: string;
  children?: React.ReactNode;
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
        {children}
      </CardHeader>
    </Card>
  );
}

export function Bar({ value, className }: { value: number; className: string }) {
  return (
    <div className="h-2 w-full min-w-16 rounded-full bg-muted">
      <div
        className={`h-2 rounded-full ${className}`}
        style={{ width: `${Math.min(value, 1) * 100}%` }}
      />
    </div>
  );
}

/** `text` with every phrase of `marks` found in it highlighted (case-insensitive). */
export function Highlighted({ text, marks }: { text: string; marks: (string | null)[] }) {
  const lower = text.toLowerCase();
  const spans = marks
    .flatMap((m) => {
      const at = m ? lower.indexOf(m.toLowerCase()) : -1;
      return at < 0 ? [] : [[at, at + m!.length] as const];
    })
    .sort((a, b) => a[0] - b[0]);
  const out: React.ReactNode[] = [];
  let i = 0;
  for (const [s, e] of spans) {
    if (s < i) continue; // overlaps the previous mark
    out.push(
      text.slice(i, s),
      <mark
        key={s}
        className="rounded bg-yellow-200/70 px-0.5 dark:bg-yellow-500/30 dark:text-inherit"
      >
        {text.slice(s, e)}
      </mark>,
    );
    i = e;
  }
  out.push(text.slice(i));
  return <>{out}</>;
}

export function Verbatim({ e, actions }: { e: Evidence; actions: React.ReactNode }) {
  const found = !!e.quote && e.text.toLowerCase().includes(e.quote.toLowerCase());
  return (
    <figure className="rounded-lg border p-3 text-sm">
      <blockquote className="leading-relaxed whitespace-pre-line">
        <Highlighted text={e.text} marks={[e.quote]} />
      </blockquote>
      {!found && e.quote && (
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

/** One VFC category in scope: why it ranks where it does, issue types, aspects, verbatims. */
export async function AspectDetail({
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
