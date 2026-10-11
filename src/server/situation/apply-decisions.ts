// Pure: PM decisions applied on top of a run's recommendations. No DB or Next imports (vitest).

export type DecisionAction = "omit" | "change_target" | "deprioritize" | "note";

export type Decision = {
  id: string;
  reqId: string | null;
  attribute: string;
  action: DecisionAction;
  operator: string | null;
  value: number | null;
  unit: string | null;
  reason: string;
  createdAt: string;
  undoneAt: string | null;
};

export type Recommended = {
  reqId: string;
  attribute: string;
  label: string;
  targetOperator: string | null;
  targetValue: number | null;
  targetUnit: string | null;
  targetCondition: string | null;
};

export type Adapted<R extends Recommended> = R & {
  /** The target after PM changes; the original stays in targetOperator/Value/Unit. */
  final: { operator: string | null; value: number | null; unit: string | null; byPm: boolean };
  deprioritized: boolean;
  notes: string[];
  decisions: Decision[];
};

export type AdaptedRun<R extends Recommended> = {
  kept: Adapted<R>[];
  omitted: (R & { reasons: string[]; decisions: Decision[] })[];
  /** Decisions about features that are not recommended requirements (notes, mostly). */
  other: Decision[];
};

/** Active decisions (not undone), oldest first, so later decisions win. */
export const active = (decisions: Decision[]) =>
  decisions.filter((d) => !d.undoneAt).toSorted((a, b) => a.createdAt.localeCompare(b.createdAt));

export function applyDecisions<R extends Recommended>(
  recommended: R[],
  decisions: Decision[],
): AdaptedRun<R> {
  const live = active(decisions);
  const byAttribute = Map.groupBy(live, (d) => d.attribute);
  const known = new Set(recommended.map((r) => r.attribute));
  const kept: Adapted<R>[] = [];
  const omitted: AdaptedRun<R>["omitted"] = [];
  for (const r of recommended) {
    const ds = byAttribute.get(r.attribute) ?? [];
    const omits = ds.filter((d) => d.action === "omit");
    if (omits.length) {
      omitted.push({ ...r, reasons: omits.map((d) => d.reason), decisions: ds });
      continue;
    }
    const change = ds.filter((d) => d.action === "change_target").at(-1);
    kept.push({
      ...r,
      final: change
        ? { operator: change.operator, value: change.value, unit: change.unit, byPm: true }
        : {
            operator: r.targetOperator,
            value: r.targetValue,
            unit: r.targetUnit,
            byPm: false,
          },
      deprioritized: ds.some((d) => d.action === "deprioritize"),
      notes: ds.filter((d) => d.action !== "omit").map((d) => d.reason),
      decisions: ds,
    });
  }
  // Deprioritized requirements move to the end, keeping their order otherwise.
  kept.sort((a, b) => Number(a.deprioritized) - Number(b.deprioritized));
  return { kept, omitted, other: live.filter((d) => !known.has(d.attribute)) };
}

/** One line per decision, for the chat and the report's decision log. */
export function describeDecision(d: Decision) {
  const what = d.reqId ? `${d.reqId} (${d.attribute})` : d.attribute;
  const action =
    d.action === "omit"
      ? "omitted"
      : d.action === "change_target"
        ? `target set to ${[d.operator, d.value, d.unit].filter((x) => x != null).join(" ")}`
        : d.action === "deprioritize"
          ? "deprioritized"
          : "note";
  return `${what}: ${action} - ${d.reason}`;
}
