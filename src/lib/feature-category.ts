/**
 * Feature categories as in the BMWow presentation (Exterior, Interior, Powertrain, Driver
 * assistance, …). Taxonomy features carry their area; feedback areas without a feature mapping
 * ("unmapped:<area>") are placed by their area name.
 */

export const CATEGORIES = [
  { key: "exterior", label: "Exterior" },
  { key: "interior", label: "Interior" },
  { key: "powertrain", label: "Powertrain" },
  { key: "driver_assistance", label: "Driver assistance" },
  { key: "digital", label: "Digital & UX" },
  { key: "ownership", label: "Ownership & business" },
  { key: "other", label: "Other" },
] as const;

export type CategoryKey = (typeof CATEGORIES)[number]["key"];

/** Taxonomy areas (python/bmwow/agent/taxonomy.yaml) → category. */
const BY_AREA: Record<string, CategoryKey> = {
  Exterior: "exterior",
  Interior: "interior",
  Powertrain: "powertrain",
  Driver_assistance: "driver_assistance",
  Digital_UX: "digital",
  Business: "ownership",
};

/** Feedback areas without a feature mapping (VFC area names, snake_case) → category. */
const BY_FEEDBACK_AREA: [RegExp, CategoryKey][] = [
  [/exterior|visibility|lighting|access|locking|keys|body/, "exterior"],
  [/interior|seats|comfort|climate|storage|luggage|materials/, "interior"],
  [/powertrain|performance|chassis|ride|handling|electrification|charging/, "powertrain"],
  [/adas|driving_assistance|safety|restraints/, "driver_assistance"],
  [/infotainment|connectivity|instruments|controls|digital/, "digital"],
  [/service|docs|support|ownership|price|cost/, "ownership"],
];

export function categoryOf(attribute: string, area: string): CategoryKey {
  if (BY_AREA[area]) return BY_AREA[area];
  const name = attribute.replace(/^unmapped:/, "");
  return BY_FEEDBACK_AREA.find(([re]) => re.test(name))?.[1] ?? "other";
}

export const categoryLabel = (key: string) =>
  CATEGORIES.find((c) => c.key === key)?.label ?? "Other";
