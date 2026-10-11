/** Assessment IDs stay stable in stored runs; these are their product-facing names. */
const LABELS: Record<string, string> = {
  gap: "Underperformance",
  demand: "Gap",
  hygiene_factor: "Must-have",
  strength: "Strength",
  unclear: "Unclear",
  not_assessed: "Not assessed",
};

export const assessmentLabel = (value: string) => LABELS[value] ?? value;

/** A stored rule suggestion starts with its assessment ID, followed by its evidence basis. */
export const assessmentSuggestion = (text: string) =>
  text.replace(/^(\w+)(?=\s*(?:\(|$))/, assessmentLabel);
