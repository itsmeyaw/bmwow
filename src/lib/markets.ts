export const EU27 = new Set(
  "AT BE BG HR CY CZ DK EE FI FR DE GR IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split(" "),
);

/** A situation run's region (ALL, EU, US, CN) → the feedback countries it covers; null = all. */
export const marketCountries = (region: string): string[] | null =>
  region === "ALL" ? null : region === "EU" ? [...EU27] : [region];
