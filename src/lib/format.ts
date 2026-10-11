const regionNames = new Intl.DisplayNames(["en"], { type: "region" });

export const countryName = (code: string | null) =>
  code ? (regionNames.of(code) ?? code) : "World";

export const pct = (x: number) => `${(x * 100).toFixed(x < 0.1 ? 1 : 0)}%`;

// Round first so tiny negatives print "0.00", not "-0.00".
const round2 = (x: number) => Number(x.toFixed(2));

export const signed = (x: number | null) =>
  x == null ? "–" : `${round2(x) > 0 ? "+" : ""}${round2(x).toFixed(2)}`;

/** Green above zero, red below, neutral at (rounded) zero. */
export const signTone = (x: number | null) =>
  x == null || round2(x) === 0
    ? ""
    : round2(x) > 0
      ? "text-emerald-600 dark:text-emerald-400"
      : "text-destructive";

// ponytail: fixed bands on the −1…+1 net scale; recalibrate if the data shifts.
const moods = [
  { min: 0.4, label: "Very good", className: "text-emerald-600 dark:text-emerald-400" },
  { min: 0.1, label: "Good", className: "text-emerald-600 dark:text-emerald-400" },
  { min: -0.1, label: "Neutral", className: "" },
  { min: -0.4, label: "Bad", className: "text-destructive" },
  { min: -Infinity, label: "Very bad", className: "text-destructive" },
];

/** Plain-word label for a net sentiment score. */
export const mood = (x: number | null) =>
  x == null ? { label: "–", className: "" } : moods.find((m) => x >= m.min)!;

export const int = (n: number) => n.toLocaleString("en");
