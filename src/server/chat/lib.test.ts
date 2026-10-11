import { describe, expect, it } from "vitest";
import { parseScope, rrf, salesMarket, TOPIC_MAX, webQuery } from "./lib";

describe("webQuery", () => {
  it("adds car and country to the topic", () => {
    expect(webQuery("in-car fridge", "X5", "Germany")).toBe("BMW X5 in-car fridge in Germany");
    expect(webQuery("in-car fridge", "BMW iX", null)).toBe("BMW iX in-car fridge");
    expect(webQuery("new SUV features 2026", null, null)).toBe("BMW new SUV features 2026");
  });

  it("strips markup, newlines and overlong text", () => {
    expect(webQuery('  "fridge"\n<script>[G70-0042]  ', null, null)).toBe(
      "BMW fridge script G70-0042",
    );
    expect(webQuery("a".repeat(500), null, null)).toBe(`BMW ${"a".repeat(TOPIC_MAX)}`);
    expect(webQuery(" \n<>{} ", "X5", "Germany")).toBeNull();
  });
});

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
