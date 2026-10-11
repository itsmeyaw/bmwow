import "server-only";
import { PDFDocument, rgb, StandardFonts, type PDFFont, type PDFPage } from "pdf-lib";
import { categoryLabel, categoryOf, sentenceLabel } from "@/lib/feature-category";
import { applyDecisions, describeDecision, type Decision } from "./apply-decisions";
import type { FeatureRow, Run } from "./queries";

/**
 * The run's recommendations adapted by the PM's decisions, as a PDF. The run itself is unchanged:
 * the report shows the system's original target next to any PM change, and a full decision log.
 */

const A4: [number, number] = [595.28, 841.89];
const MARGIN = 50;
const INK = rgb(0.1, 0.1, 0.12);
const MUTED = rgb(0.42, 0.42, 0.46);
const ACCENT = rgb(0.75, 0.2, 0.15);

/** Standard PDF fonts only cover WinAnsi; map common symbols, drop what cannot be shown. */
function clean(text: string) {
  return text
    .replaceAll("≤", "<=")
    .replaceAll("≥", ">=")
    .replaceAll("→", "->")
    .replaceAll("×", "x")
    .replaceAll(" ", " ")
    .replace(/[^\x20-\x7e -ÿ–—‘’“”•…€·]/g, "?");
}

class Writer {
  page!: PDFPage;
  y = 0;
  pages: PDFPage[] = [];
  constructor(
    private doc: PDFDocument,
    readonly font: PDFFont,
    private bold: PDFFont,
  ) {
    this.newPage();
  }

  newPage() {
    this.page = this.doc.addPage(A4);
    this.pages.push(this.page);
    this.y = A4[1] - MARGIN;
  }

  private ensure(height: number) {
    if (this.y - height < MARGIN + 20) this.newPage();
  }

  /** Wrapped paragraph; returns nothing, advances the cursor. */
  text(raw: string, { size = 10, bold = false, color = INK, indent = 0, gap = 4 } = {}) {
    const font = bold ? this.bold : this.font;
    const width = A4[0] - 2 * MARGIN - indent;
    const words = clean(raw).split(/\s+/);
    const lines: string[] = [];
    let line = "";
    for (const w of words) {
      const next = line ? `${line} ${w}` : w;
      if (font.widthOfTextAtSize(next, size) > width && line) {
        lines.push(line);
        line = w;
      } else line = next;
    }
    if (line) lines.push(line);
    const lead = size * 1.35;
    for (const l of lines) {
      this.ensure(lead);
      this.page.drawText(l, { x: MARGIN + indent, y: this.y - size, size, font, color });
      this.y -= lead;
    }
    this.y -= gap;
  }

  rule() {
    this.ensure(10);
    this.page.drawLine({
      start: { x: MARGIN, y: this.y },
      end: { x: A4[0] - MARGIN, y: this.y },
      thickness: 0.5,
      color: rgb(0.85, 0.85, 0.87),
    });
    this.y -= 10;
  }

  heading(text: string) {
    this.ensure(40);
    this.y -= 6;
    this.text(text, { size: 13, bold: true, gap: 6 });
  }
}

/** Reasoning text without its evidence ids ([F-…], [fb:…], [kg:…], [web:…]); the app keeps them. */
const prose = (text: string) =>
  text.replace(/\s*\[(?:[^\]]*(?:fb:|F-|kg:|web:|evidence:)[^\]]*)\]/g, "").trim();

const fmtTarget = (op: string | null, value: number | null, unit: string | null) =>
  value == null ? "set by PM" : [op, value.toLocaleString("en"), unit].filter(Boolean).join(" ");

const reqOrder = (r: { reqId: string | null }) => Number(r.reqId?.replace(/\D/g, "") || 9999);

export async function buildReport(
  run: Run,
  features: FeatureRow[],
  decisions: Decision[],
): Promise<Uint8Array> {
  const doc = await PDFDocument.create();
  doc.setTitle(clean(`Requirement recommendations ${run.modelCode} ${run.region}`));
  doc.setCreator("BMWow situation analysis");
  const w = new Writer(
    doc,
    await doc.embedFont(StandardFonts.Helvetica),
    await doc.embedFont(StandardFonts.HelveticaBold),
  );

  const recommended = features
    .filter((f): f is FeatureRow & { reqId: string } => f.reqId != null)
    .toSorted((a, b) => reqOrder(a) - reqOrder(b));
  const adapted = applyDecisions(recommended, decisions);
  const live = decisions.filter((d) => !d.undoneAt);
  const region = run.region === "ALL" ? "all regions" : run.region;
  const count = (a: Decision["action"]) => live.filter((d) => d.action === a).length;

  w.text("Requirement recommendations after PM review", { size: 18, bold: true, gap: 2 });
  w.text(
    `${run.modelCode} · ${run.modelName ?? ""} · ${region} · run ${run.runId} · generated ${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC`,
    { size: 9, color: MUTED, gap: 10 },
  );
  w.text(
    `The system recommended ${recommended.length} requirements. In the discussion the PM omitted ${adapted.omitted.length}, changed ${count("change_target")} target(s), deprioritized ${count("deprioritize")} and added ${count("note")} note(s). ${adapted.kept.length} requirements remain.`,
    { size: 10, gap: 8 },
  );
  w.rule();

  w.heading(`Recommended requirements (${adapted.kept.length})`);
  adapted.kept.forEach((r, i) => {
    const category = categoryLabel(categoryOf(r.attribute, r.area));
    w.text(
      `${i + 1}. ${r.reqId} · ${sentenceLabel(r.label)} (${category}) · ${r.assessment}${r.deprioritized ? " · deprioritized by PM" : ""}`,
      { size: 11, bold: true, gap: 2 },
    );
    if (r.requirement) w.text(r.requirement, { indent: 12, gap: 2 });
    const original = fmtTarget(r.targetOperator, r.targetValue, r.targetUnit);
    w.text(
      r.final.byPm
        ? `Target: ${fmtTarget(r.final.operator, r.final.value, r.final.unit)} (set by PM; system proposed ${original}${r.targetCondition ? `, ${r.targetCondition}` : ""})`
        : `Target: ${original}${r.targetCondition ? ` (${r.targetCondition})` : ""}`,
      { indent: 12, size: 9.5, bold: r.final.byPm, color: r.final.byPm ? ACCENT : INK, gap: 2 },
    );
    if (r.whatExactly)
      w.text(`Why: ${prose(r.whatExactly)}`, { indent: 12, size: 9, color: MUTED, gap: 2 });
    for (const n of r.notes) w.text(`PM: ${n}`, { indent: 12, size: 9, color: ACCENT, gap: 2 });
    w.y -= 6;
  });
  if (!adapted.kept.length) w.text("None.", { color: MUTED });

  if (adapted.omitted.length) {
    w.heading(`Omitted by the PM (${adapted.omitted.length})`);
    for (const r of adapted.omitted) {
      w.text(`${r.reqId} · ${sentenceLabel(r.label)}`, { size: 10.5, bold: true, gap: 2 });
      if (r.requirement)
        w.text(`System recommendation: ${r.requirement}`, {
          indent: 12,
          size: 9,
          color: MUTED,
          gap: 2,
        });
      for (const reason of r.reasons)
        w.text(`Reason: ${reason}`, { indent: 12, size: 9.5, color: ACCENT, gap: 2 });
      w.y -= 4;
    }
  }

  if (adapted.other.length) {
    w.heading("Other PM notes");
    for (const d of adapted.other) w.text(`- ${describeDecision(d)}`, { size: 9.5 });
  }

  w.heading("Decision log");
  if (!decisions.length) w.text("No decisions were recorded.", { color: MUTED });
  for (const d of decisions)
    w.text(
      `${d.createdAt.slice(0, 16).replace("T", " ")}  ${describeDecision(d)}${d.undoneAt ? "  (undone)" : ""}`,
      { size: 9, color: d.undoneAt ? MUTED : INK, gap: 2 },
    );

  w.heading("How these recommendations were made");
  w.text(
    "Four agents collected evidence for the car and region: our current model (price list, customer studies, sales), competitors in the same segment (values compared only like-for-like: same unit, test standard and powertrain), customer feedback shares with 95% intervals, and market and regulation trends. Code computed every number; an LLM judged each feature with a fixed rubric and code checked the judgment; targets come from the competitor median or today's value. The PM's decisions above adapt the recommendations; the recorded analysis is unchanged and every claim stays traceable to its sources in the BMWow situation analysis.",
    { size: 9, color: MUTED },
  );

  w.pages.forEach((p, i) =>
    p.drawText(clean(`${run.modelCode} · ${region} · page ${i + 1} of ${w.pages.length}`), {
      x: MARGIN,
      y: 28,
      size: 8,
      font: w.font,
      color: MUTED,
    }),
  );
  return doc.save();
}
