import { Badge } from "@/components/ui/badge";
import { assessmentLabel } from "@/lib/assessment";
import { pct } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * What each assessment means; shown as badge title and in the legend. `bar` colours CSS bars,
 * `fill` colours charts.
 */
export const ASSESSMENTS: Record<
  string,
  { label: string; className: string; hint: string; bar: string; fill: string }
> = {
  gap: {
    label: assessmentLabel("gap"),
    className: "bg-destructive/10 text-destructive",
    hint: "A comparable benchmark shows we fall behind competitors.",
    bar: "bg-destructive",
    fill: "var(--destructive)",
  },
  demand: {
    label: assessmentLabel("demand"),
    className: "bg-sky-500/10 text-sky-700 dark:text-sky-300",
    hint: "An unmet customer need: customers report problems, ask for more, or the market signals a need.",
    bar: "bg-sky-500",
    fill: "var(--color-sky-500)",
  },
  hygiene_factor: {
    label: "Must-have",
    className: "bg-amber-500/10 text-amber-700 dark:text-amber-300",
    hint: "A basic expectation: customers complain, but competitors are no better. Keep the level, fix the complaints.",
    bar: "bg-amber-500",
    fill: "var(--color-amber-500)",
  },
  strength: {
    label: "Strength",
    className: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
    hint: "We lead, or customers praise it. Keep it.",
    bar: "bg-emerald-500",
    fill: "var(--color-emerald-500)",
  },
  unclear: {
    label: "Unclear",
    className: "bg-muted text-muted-foreground",
    hint: "Evidence too thin or contradictory to decide.",
    bar: "bg-muted-foreground/25",
    fill: "color-mix(in oklch, var(--muted-foreground) 25%, transparent)",
  },
  not_assessed: {
    label: "Not assessed",
    className: "bg-muted text-muted-foreground",
    hint: "Not assessed in this run.",
    bar: "bg-muted-foreground/25",
    fill: "color-mix(in oklch, var(--muted-foreground) 25%, transparent)",
  },
};

/** The decided verdicts, in display order. */
export const VERDICTS = ["gap", "demand", "hygiene_factor", "strength"] as const;

/** Stored texts say "hygiene_factor"; the UI says "must-have". */
export const unjargon = (text: string) =>
  text
    .replace(/hygiene[_ ]factors?/gi, "must-have")
    .replace(/\((gap|demand)\)/g, (_, id: string) => `(${assessmentLabel(id)})`);

/** A requirement statement without its "The successor should improve" lead, for one-line display. */
export const plainRequirement = (text: string) => {
  const s = unjargon(text)
    .replace(/\bthe successor should (improve|introduce|retain|remove)\s+(the\s+)?/i, "")
    .replace(/^(improve|introduce|retain|remove)\s+/i, "");
  return s.charAt(0).toUpperCase() + s.slice(1);
};

export function AssessmentBadge({ value, method }: { value: string; method?: string }) {
  const a = ASSESSMENTS[value] ?? ASSESSMENTS.unclear;
  return (
    <Badge
      variant="secondary"
      className={cn("font-medium", a.className)}
      title={`${a.hint}${method === "rule" ? " (Rule-based: computed from the numbers, low certainty.)" : ""}`}
    >
      {a.label}
      {method === "rule" && <span className="opacity-60">· rule</span>}
    </Badge>
  );
}

/** "intuitive ux" -> "Intuitive UX": first letter up, known acronyms in capitals. */
export const sentence = (label: string) =>
  (label.charAt(0).toUpperCase() + label.slice(1)).replace(/\b(ux|adas|ev|bev|phev)\b/gi, (m) =>
    m.toUpperCase(),
  );

export const INTENTS: Record<string, string> = {
  introduce: "Introduce",
  improve: "Improve",
  retain: "Retain",
  remove: "Remove",
};

/** A number as written in the data: no trailing zeros, thousands separated. */
export const num = (x: number | null | undefined) =>
  x == null ? "–" : x.toLocaleString("en", { maximumFractionDigits: 2 });

export function target(
  op: string | null,
  value: number | null,
  unit: string | null,
  condition: string | null,
) {
  if (value == null) return null;
  return `${op ?? ""} ${num(value)} ${unit ?? ""}${condition ? ` · ${condition}` : ""}`.trim();
}

const TONES: Record<string, string> = {
  problem: "bg-destructive",
  request: "bg-sky-500",
  strength: "bg-emerald-500",
  neutral: "bg-muted-foreground",
};

export const DIRECTION_LABEL: Record<string, string> = {
  problem: "Problem",
  request: "Request",
  strength: "Praise",
  neutral: "Neutral",
};

/** A share with its 95% interval: the bar is the share, the darker band the interval. */
export function ShareBar({
  share,
  ciLow,
  ciHigh,
  direction,
  max,
}: {
  share: number;
  ciLow: number;
  ciHigh: number;
  direction: string;
  max: number;
}) {
  const scale = (x: number) => `${Math.min(x / max, 1) * 100}%`;
  return (
    <div className="relative h-2.5 w-full min-w-24 rounded-full bg-muted">
      <div
        className={cn("absolute inset-y-0 left-0 rounded-full opacity-80", TONES[direction])}
        style={{ width: scale(share) }}
      />
      <div
        className="absolute inset-y-[-3px] rounded-sm border border-foreground/40"
        style={{ left: scale(ciLow), width: `calc(${scale(ciHigh)} - ${scale(ciLow)})` }}
        title={`95% interval ${pct(ciLow)}–${pct(ciHigh)}`}
      />
    </div>
  );
}

export function Section({
  title,
  hint,
  children,
  empty,
}: {
  title: string;
  hint?: string;
  children?: React.ReactNode;
  empty?: string | false;
}) {
  return (
    <section className="flex flex-col gap-3">
      <div>
        <h3 className="text-sm font-medium">{title}</h3>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </div>
      {empty ? <p className="text-sm text-muted-foreground">{empty}</p> : children}
    </section>
  );
}

export function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-muted/50 p-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-medium tabular-nums">{value}</dd>
    </div>
  );
}

/** Reasoning text with its [id, id] citations rendered as small chips. */
export function Cited({ text }: { text: string }) {
  const parts = text.split(/(\[[^\]]+\])/g);
  return (
    <p className="text-sm leading-relaxed">
      {parts.map((p, i) =>
        p.startsWith("[") && p.endsWith("]") ? (
          <span
            key={i}
            className="mx-0.5 inline-block rounded bg-muted px-1 align-baseline font-mono text-[10px] text-muted-foreground"
            title={p.slice(1, -1)}
          >
            {p.slice(1, -1).split(",").length} src
          </span>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </p>
  );
}

/** The decided verdicts of one run as a single segmented bar; unclear ones only in the tooltip. */
export function VerdictStrip({ counts }: { counts: Record<string, number> }) {
  const parts = VERDICTS.map((k) => ({ k, n: counts[k] ?? 0 }));
  const total = parts.reduce((s, p) => s + p.n, 0) || 1;
  const unclear = (counts.unclear ?? 0) + (counts.not_assessed ?? 0);
  return (
    <div
      className="flex h-2 w-full min-w-16 gap-px overflow-hidden rounded-full bg-muted"
      title={[...parts.map((p) => `${ASSESSMENTS[p.k].label}: ${p.n}`), `Unclear: ${unclear}`].join(
        " · ",
      )}
    >
      {parts.map(
        (p) =>
          p.n > 0 && (
            <div
              key={p.k}
              className={ASSESSMENTS[p.k].bar}
              style={{ width: `${(p.n / total) * 100}%` }}
            />
          ),
      )}
    </div>
  );
}

/** Colour key for VerdictStrip; each label explains itself on hover. */
export function VerdictLegend() {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {VERDICTS.map((k) => (
        <li key={k} className="flex items-center gap-1.5" title={ASSESSMENTS[k].hint}>
          <span className={cn("size-2.5 rounded-sm", ASSESSMENTS[k].bar)} />
          {ASSESSMENTS[k].label}
        </li>
      ))}
    </ul>
  );
}
