import { describe, expect, it } from "vitest";
import { parseScope, rrf, salesMarket } from "./lib";

describe("parseScope", () => {
  it("maps URL values to a Scope", () => {
    expect(parseScope({ derivate: "G70", region: "US", engine: "BEV" })).toEqual({
      derivate: "G70",
      country: "US",
      engine: "BEV",
    });
  });

  it("treats missing or malformed values as all", () => {
    const all = { derivate: null, country: null, engine: null };
    expect(parseScope(undefined)).toEqual(all);
    expect(parseScope("G70")).toEqual(all);
    expect(parseScope({ derivate: "g70'; drop", region: "USA", engine: "BEVE" })).toEqual(all);
    expect(parseScope({ derivate: "G70", region: null })).toEqual({ ...all, derivate: "G70" });
  });
});

describe("salesMarket", () => {
  it("groups countries into sales markets", () => {
    expect(salesMarket("DE")).toBe("EU");
    expect(salesMarket("US")).toBe("US");
    expect(salesMarket("CN")).toBe("CN");
    expect(salesMarket("GB")).toBe("RoW");
    expect(salesMarket(null)).toBeNull();
  });
});

describe("rrf", () => {
  it("ranks items found by both lists above single-list hits", () => {
    expect(
      rrf([
        ["a", "b", "c"],
        ["c", "d"],
      ]),
    ).toEqual(["c", "a", "b", "d"]);
  });

  it("handles empty lists", () => {
    expect(rrf([[], []])).toEqual([]);
    expect(rrf([["a"], []])).toEqual(["a"]);
  });
});
