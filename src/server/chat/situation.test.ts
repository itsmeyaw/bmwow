import { describe, expect, it } from "vitest";
import { feedbackCountry, parseSituationPage, shortFeedbackId } from "./situation-lib";

describe("parseSituationPage", () => {
  it("reads a car run page", () => {
    expect(
      parseSituationPage({
        view: "situation",
        derivate: "G60",
        region: "US",
        feature: "fast_charging",
      }),
    ).toEqual({ derivate: "G60", region: "US", feature: "fast_charging" });
  });

  it("treats the overview as no car", () => {
    expect(parseSituationPage({ view: "situation" })).toEqual({
      derivate: null,
      region: null,
      feature: null,
    });
  });

  it("drops malformed values instead of trusting them", () => {
    expect(
      parseSituationPage({
        view: "situation",
        derivate: "g60; drop",
        region: "XX",
        feature: "a b",
      }),
    ).toEqual({ derivate: null, region: null, feature: null });
  });

  it("is null outside /situation", () => {
    expect(parseSituationPage({ derivate: "G60", region: "US" })).toBeNull();
    expect(parseSituationPage(null)).toBeNull();
  });
});

describe("helpers", () => {
  it("maps regions to feedback countries", () => {
    expect(feedbackCountry("US")).toBe("US");
    expect(feedbackCountry("EU")).toBeNull();
    expect(feedbackCountry("ALL")).toBeNull();
  });

  it("shortens stored feedback ids to the cited form", () => {
    expect(shortFeedbackId("fb:evidence:bmw-feedback:G60-0309")).toBe("G60-0309");
  });
});
