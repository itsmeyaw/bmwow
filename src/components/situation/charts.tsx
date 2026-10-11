"use client";

import { useRouter } from "next/navigation";
import { Bar, BarChart, Cell, Label, Pie, PieChart, ReferenceLine, XAxis, YAxis } from "recharts";
import { ASSESSMENTS, VERDICTS } from "@/components/situation/parts";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { int, pct } from "@/lib/format";

/** One-line axis label; recharts' default tick wraps long category names. */
const tick =
  (format: (v: string) => string = (v) => v) =>
  ({ x, y, payload }: { x?: number | string; y?: number | string; payload: { value: string } }) => (
    <text x={x} y={y} dy={4} textAnchor="end" className="fill-muted-foreground text-xs">
      {format(payload.value)}
    </text>
  );
const verdictConfig = Object.fromEntries(
  VERDICTS.map((k) => [k, { label: ASSESSMENTS[k].label, color: ASSESSMENTS[k].fill }]),
) satisfies ChartConfig;

/** Donut of feature verdicts with the total in the middle and a legend with counts. */
export function VerdictDonut({ counts }: { counts: Record<string, number> }) {
  const data = VERDICTS.map((k) => ({
    key: k,
    n: counts[k] ?? 0,
    fill: `var(--color-${k})`,
  })).filter((d) => d.n);
  const total = data.reduce((s, d) => s + d.n, 0);
  return (
    <div className="flex items-center gap-6">
      <ChartContainer config={verdictConfig} className="aspect-square h-40 shrink-0">
        <PieChart>
          <ChartTooltip content={<ChartTooltipContent hideLabel nameKey="key" />} />
          <Pie
            data={data}
            dataKey="n"
            nameKey="key"
            innerRadius={50}
            outerRadius={72}
            strokeWidth={2}
          >
            <Label
              content={({ viewBox }) =>
                viewBox && "cx" in viewBox ? (
                  <text x={viewBox.cx} y={viewBox.cy} textAnchor="middle" dominantBaseline="middle">
                    <tspan
                      x={viewBox.cx}
                      dy="-0.2em"
                      className="fill-foreground text-2xl font-semibold"
                    >
                      {total}
                    </tspan>
                    <tspan x={viewBox.cx} dy="1.6em" className="fill-muted-foreground text-xs">
                      features
                    </tspan>
                  </text>
                ) : null
              }
            />
          </Pie>
        </PieChart>
      </ChartContainer>
      <ul className="flex flex-col gap-1.5 text-sm">
        {VERDICTS.map((k) => (
          <li key={k} className="flex items-center gap-2" title={ASSESSMENTS[k].hint}>
            <span className={`size-2.5 rounded-sm ${ASSESSMENTS[k].bar}`} />
            <span className="w-36">{ASSESSMENTS[k].label}</span>
            <span className="font-medium tabular-nums">{int(counts[k] ?? 0)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export type CategoryBar = { key: string; label: string; href: string } & Record<
  (typeof VERDICTS)[number],
  number
>;

/** Requirements per category, stacked by verdict. A click filters the page by that category. */
export function CategoryChart({ rows, active }: { rows: CategoryBar[]; active: string | null }) {
  const router = useRouter();
  const open = (d: { payload?: CategoryBar }) =>
    d.payload && router.push(d.payload.href, { scroll: false });
  return (
    <ChartContainer
      config={verdictConfig}
      className="aspect-auto w-full"
      style={{ height: rows.length * 36 + 8 }}
    >
      <BarChart data={rows} layout="vertical" margin={{ left: 0, right: 8 }} barCategoryGap={8}>
        <XAxis type="number" hide allowDecimals={false} />
        <YAxis
          type="category"
          dataKey="label"
          width={150}
          tickLine={false}
          axisLine={false}
          tick={tick((label) => {
            const r = rows.find((x) => x.label === label);
            return r ? `${label}  ${VERDICTS.reduce((s, k) => s + r[k], 0)}` : label;
          })}
        />
        <ChartTooltip cursor={false} content={<ChartTooltipContent />} />
        {VERDICTS.map((k) => (
          <Bar
            key={k}
            dataKey={k}
            stackId="v"
            fill={`var(--color-${k})`}
            className="cursor-pointer"
            onClick={open}
          >
            {rows.map((r) => (
              <Cell key={r.key} fillOpacity={active && r.key !== active ? 0.25 : 1} />
            ))}
          </Bar>
        ))}
      </BarChart>
    </ChartContainer>
  );
}

export type VoiceRow = {
  label: string;
  /** Minus the share of feedback with a problem, so it draws to the left. */
  problem: number;
  praise: number;
  problemN: number;
  praiseN: number;
  problemHref: string;
  praiseHref: string;
};

const voiceConfig = {
  problem: { label: "Complaints", color: "var(--destructive)" },
  praise: { label: "Praise", color: "var(--color-emerald-500)" },
} satisfies ChartConfig;

/** Complaints (left) against praise (right) per category; a click opens the verbatims. */
export function VoiceChart({ rows }: { rows: VoiceRow[] }) {
  const router = useRouter();
  const go = (key: "problemHref" | "praiseHref") => (d: { payload?: VoiceRow }) =>
    d.payload && router.push(d.payload[key], { scroll: false });
  return (
    <div className="flex flex-col gap-1">
      <div className="ml-[190px] flex justify-between text-xs text-muted-foreground">
        <span>← Complaints</span>
        <span>Praise →</span>
      </div>
      <ChartContainer
        config={voiceConfig}
        className="aspect-auto w-full"
        style={{ height: rows.length * 32 + 28 }}
      >
        <BarChart
          data={rows}
          layout="vertical"
          stackOffset="sign"
          margin={{ left: 0, right: 8 }}
          barCategoryGap={6}
        >
          <XAxis
            type="number"
            tickFormatter={(v: number) => (v ? pct(Math.abs(v)) : "0")}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            type="category"
            dataKey="label"
            width={190}
            tickLine={false}
            axisLine={false}
            tick={tick()}
          />
          <ReferenceLine x={0} className="stroke-border" />
          <ChartTooltip
            cursor={false}
            content={
              <ChartTooltipContent
                formatter={(value, name, item) => {
                  const r = item.payload as VoiceRow;
                  const n = name === "problem" ? r.problemN : r.praiseN;
                  return (
                    <div className="flex w-full items-center gap-2">
                      <span
                        className="size-2.5 rounded-sm"
                        style={{ background: `var(--color-${name})` }}
                      />
                      <span className="text-muted-foreground">
                        {voiceConfig[name as keyof typeof voiceConfig].label}
                      </span>
                      <span className="ml-auto font-mono tabular-nums">
                        {pct(Math.abs(Number(value)))} ({int(n)})
                      </span>
                    </div>
                  );
                }}
              />
            }
          />
          <Bar
            dataKey="problem"
            stackId="v"
            fill="var(--color-problem)"
            // Negative bars have negative width, so Recharts mirrors the radii.
            radius={[0, 4, 4, 0]}
            className="cursor-pointer"
            onClick={go("problemHref")}
          />
          <Bar
            dataKey="praise"
            stackId="v"
            fill="var(--color-praise)"
            radius={[0, 4, 4, 0]}
            className="cursor-pointer"
            onClick={go("praiseHref")}
          />
        </BarChart>
      </ChartContainer>
    </div>
  );
}
