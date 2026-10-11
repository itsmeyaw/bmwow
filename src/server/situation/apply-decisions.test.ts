import { describe, expect, it } from "vitest";
import { applyDecisions, describeDecision, type Decision } from "./apply-decisions";

const req = (n: number, attribute: string) => ({
  reqId: `REQ-${n}`,
  attribute,
  label: attribute,
  targetOperator: ">=",
  targetValue: 100,
  targetUnit: "km",
  targetCondition: "wltp",
});

let t = 0;
const decision = (attribute: string, action: Decision["action"], extra: Partial<Decision> = {}) =>
  ({
    id: `d${++t}`,
    reqId: null,
    attribute,
    action,
    operator: null,
    value: null,
    unit: null,
    reason: `reason ${t}`,
    createdAt: `2026-10-11T10:00:${String(t).padStart(2, "0")}`,
    undoneAt: null,
    ...extra,
  }) satisfies Decision;

describe("applyDecisions", () => {
  const recs = [req(1, "range"), req(2, "roof"), req(3, "charging")];

  it("omits, changes targets, deprioritizes and keeps notes", () => {
    const out = applyDecisions(recs, [
      decision("range", "omit"),
      decision("charging", "change_target", { operator: "<=", value: 25, unit: "min" }),
      decision("roof", "deprioritize"),
      decision("seats", "note"),
    ]);
    expect(out.omitted.map((r) => r.attribute)).toEqual(["range"]);
    expect(out.kept.map((r) => r.attribute)).toEqual(["charging", "roof"]); // deprioritized last
    expect(out.kept[0].final).toEqual({ operator: "<=", value: 25, unit: "min", byPm: true });
    expect(out.kept[0].targetValue).toBe(100); // the system's target stays for comparison
    expect(out.other.map((d) => d.attribute)).toEqual(["seats"]);
  });

  it("ignores undone decisions and lets the latest target win", () => {
    const out = applyDecisions(recs, [
      decision("range", "omit", { undoneAt: "2026-10-11T11:00:00" }),
      decision("range", "change_target", { operator: ">=", value: 600, unit: "km" }),
      decision("range", "change_target", { operator: ">=", value: 650, unit: "km" }),
    ]);
    expect(out.omitted).toEqual([]);
    expect(out.kept.find((r) => r.attribute === "range")?.final.value).toBe(650);
  });

  it("describes a decision in one line", () => {
    const d = decision("charging", "change_target", {
      reqId: "REQ-3",
      operator: "<=",
      value: 25,
      unit: "min",
      reason: "supplier limit",
    });
    expect(describeDecision(d)).toBe("REQ-3 (charging): target set to <= 25 min - supplier limit");
  });
});
