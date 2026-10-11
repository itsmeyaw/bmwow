import "server-only";
import { openai } from "@ai-sdk/openai";
import {
  convertToModelMessages,
  createUIMessageStreamResponse,
  isStepCount,
  streamText,
  toUIMessageStream,
  tool,
  type UIMessage,
} from "ai";
import { z } from "zod";
import { countryName, pct, signed } from "@/lib/format";
import {
  getCategoryDetail,
  getEvidence,
  getRanking,
  getSales,
  getScopeOptions,
  getSummary,
  listCars,
  type Ranking,
  type Sale,
  type Scope,
} from "@/server/analysis/queries";
import { parseScope, salesMarket } from "@/server/chat/lib";
import { searchFeedback } from "@/server/chat/search";

// ponytail: falls back to the preprocessing model; set LLM_STRONG to pick the chat model.
const MODEL = process.env.LLM_STRONG || "gpt-6-luna";

const INSTRUCTIONS = `You are the BMWow analysis assistant. Product teams at BMW ask you about customer feedback on their cars.

## Data
- Feedback: one customer verbatim, tagged with car (derivate code such as G70), country (ISO code) and engine type (BEV, PHEV, ICE).
- Aspects are extracted from each feedback. Each has a VFC Category (e.g. "Electrification & Charging"), a sentiment, an issue type and a quote.
- The page ranks VFC Categories by priority = reach × severity.
  - reach: share of in-scope feedback with at least one negative aspect in the category.
  - severity: mean |sentiment score| of those negative aspects, 0–1.
  - Ties go to the category with more negative feedback. Priority is shown ×100, as on the page.
  - demand: feedback with a Feature Request in the category. It is not part of priority.
  - net: mean sentiment score, −1…+1.
- Sales: volume per car and sales market (EU, US, CN, RoW). 2024 and 2025 are actuals, 2030 is a forecast. Sales has no engine split; when an engine filter is set, say the volumes cover all powertrains. If a car or market has no sales row, say there is no sales data rather than guessing.

## Answering
- "Current page" below is what the user is looking at. "This car", "here" and ranks like "second" refer to it.
- To explain a rank, compare the category's reach and severity with its neighbours: why it sits above the next one and below the previous one.
- "Next iteration" means the next vehicle generation or LCI of the car. Recommend from the top priorities, demand and evidence. Weigh by the sales volume and 2030 trend of the affected markets when it changes the picture, and say that you did.
- Ground claims about what customers say in verbatims returned by searchFeedback or getEvidence. Cite each such claim with the feedback id in square brackets, e.g. [G70-0042]. Only cite ids that a tool returned. Never invent ids, quotes or numbers.
- Tools take an explicit scope. Pass the current page's values unless the user asks about another car, country or engine; null means all.
- If the data cannot answer the question, say so.
- Answer in the user's language. Quote verbatims in their original language.
- Be concise: short paragraphs and bullets; a table only when comparing.`;

const fmtScope = (s: Scope) =>
  [s.derivate ?? "All cars", countryName(s.country), s.engine ?? "All engines"].join(" · ");

function rankingTable(r: Ranking) {
  const head =
    "| # | Category | Priority | Reach | Severity | Negative | Positive | Demand | Net | Top issue |\n|---|---|---|---|---|---|---|---|---|---|";
  const body = r.rows.map(
    (x, i) =>
      `| ${i + 1} | ${x.category} | ${(x.priority * 100).toFixed(1)} | ${pct(x.reach)} | ${x.severity.toFixed(2)} | ${x.negative} | ${x.positive} | ${x.demand} | ${signed(x.net)} | ${x.topIssue ?? "–"} |`,
  );
  return `${head}\n${body.join("\n")}\n${r.total} feedback in scope; ${r.unclassified} with unclassified aspects are not ranked.`;
}

function salesTable(sales: Sale[], derivate: string | null) {
  const rows = derivate ? sales.filter((s) => s.model === derivate) : sales;
  if (!rows.length) return derivate ? `No sales data for ${derivate}.` : "No sales data.";
  const total = (model: string, k: "v2025" | "v2030") =>
    sales.filter((s) => s.model === model).reduce((n, s) => n + s[k], 0) || 1;
  return [
    "| Car | Market | 2024 | 2025 | 2030 (forecast) | Share of car 2025 | Share of car 2030 |",
    "|---|---|---|---|---|---|---|",
    ...rows.map(
      (s) =>
        `| ${s.model} | ${s.market} | ${s.v2024} | ${s.v2025} | ${s.v2030} | ${pct(s.v2025 / total(s.model, "v2025"))} | ${pct(s.v2030 / total(s.model, "v2030"))} |`,
    ),
  ].join("\n");
}

/** The page the user is on, as text for the system prompt. Built server-side from scope ids only. */
async function pageContext(scope: Scope): Promise<string> {
  const [cars, sales, summary, ranking] = await Promise.all([
    listCars(),
    getSales(),
    getSummary(scope),
    getRanking(scope),
  ]);
  const carList = cars
    .map(
      (c) =>
        `- ${c.derivate} (${c.name ?? "?"}): ${c.feedback} feedback, engines ${c.engines.join("/")}`,
    )
    .join("\n");
  const head = `Scope: ${fmtScope(scope)} (derivate=${scope.derivate}, country=${scope.country}, engine=${scope.engine})
Feedback: ${summary.feedback}; with a negative aspect: ${summary.negative}; net sentiment: ${signed(summary.net)}`;

  if (!scope.derivate) {
    const tops = await Promise.all(
      cars.map(async (c) => {
        const top = (await getRanking({ ...scope, derivate: c.derivate })).rows[0];
        return `- ${c.derivate}: ${top ? `${top.category} (priority ${(top.priority * 100).toFixed(1)}, reach ${pct(top.reach)})` : "no ranked category"}`;
      }),
    );
    return `# Current page: overview of all cars
${head}

## Cars
${carList}

## #1 priority per car
${tops.join("\n")}

## Ranking across all cars
${rankingTable(ranking)}

## Sales
${salesTable(sales, null)}`;
  }

  const options = await getScopeOptions(scope.derivate);
  const market = salesMarket(scope.country);
  return `# Current page: ${scope.derivate} analysis
${head}
Countries with feedback for this car: ${options.countries.map((o) => `${o.value} (${o.n})`).join(", ")}
Engines with feedback for this car: ${options.engines.map((o) => `${o.value} (${o.n})`).join(", ")}

## Priority ranking ("What to improve first")
${rankingTable(ranking)}

## Sales
${market ? `The current country ${scope.country} belongs to sales market ${market}.` : "No country filter: all markets apply."}
${salesTable(sales, scope.derivate)}

## Other cars
${carList}`;
}

const scopeInput = {
  derivate: z.string().nullable().describe("Car derivate code, e.g. G70. null = all cars."),
  country: z.string().nullable().describe("ISO 3166-1 alpha-2 country code. null = all countries."),
  engine: z.enum(["BEV", "PHEV", "ICE"]).nullable().describe("null = all engines."),
};
const toScope = (i: { derivate: string | null; country: string | null; engine: string | null }) =>
  parseScope({ derivate: i.derivate, region: i.country, engine: i.engine });

const tools = {
  searchFeedback: tool({
    description:
      "Find customer verbatims relevant to a question (semantic + keyword search). Use it to ground claims about what customers say.",
    inputSchema: z.object({
      query: z.string().describe("What to look for, in natural language."),
      ...scopeInput,
      category: z.string().nullable().describe("Exact VFC Category name, or null for any."),
      sentiment: z.enum(["Negative", "Positive"]).nullable(),
      limit: z.number().int().min(1).max(15).describe("How many verbatims, 8 is typical."),
    }),
    execute: ({ query, category, sentiment, limit, ...s }) =>
      searchFeedback(query, toScope(s), { category, sentiment, limit }),
  }),
  getRanking: tool({
    description:
      "Priority ranking of VFC Categories for any scope, e.g. to compare countries or engines.",
    inputSchema: z.object(scopeInput),
    execute: async (s) => rankingTable(await getRanking(toScope(s))),
  }),
  getCategoryDetail: tool({
    description: "Issue types and the most mentioned aspect terms of one VFC Category in a scope.",
    inputSchema: z.object({ ...scopeInput, category: z.string() }),
    execute: ({ category, ...s }) => getCategoryDetail(toScope(s), category),
  }),
  getEvidence: tool({
    description: "Strongest verbatims for one VFC Category and sentiment in a scope.",
    inputSchema: z.object({
      ...scopeInput,
      category: z.string(),
      sentiment: z.enum(["Negative", "Positive"]),
      limit: z.number().int().min(1).max(15),
    }),
    execute: ({ category, sentiment, limit, ...s }) =>
      getEvidence(toScope(s), category, sentiment, limit),
  }),
};

/** Earlier questions may come from other pages; say which, so "this car" stays unambiguous. */
function tagPages(messages: UIMessage[]): UIMessage[] {
  return messages.map((m) => {
    const page = (m.metadata as { page?: unknown } | undefined)?.page;
    if (m.role !== "user" || !page) return m;
    return {
      ...m,
      parts: [{ type: "text", text: `(Asked on: ${fmtScope(parseScope(page))})` }, ...m.parts],
    };
  });
}

export async function chat(messages: UIMessage[], page: unknown): Promise<Response> {
  let scope = parseScope(page);
  if (scope.derivate && !(await listCars()).some((c) => c.derivate === scope.derivate))
    scope = { derivate: null, country: null, engine: null };

  const result = streamText({
    model: openai(MODEL),
    instructions: `${INSTRUCTIONS}\n\n${await pageContext(scope)}`,
    messages: await convertToModelMessages(tagPages(messages)),
    tools,
    stopWhen: isStepCount(6),
  });
  return createUIMessageStreamResponse({ stream: toUIMessageStream({ stream: result.stream }) });
}
