import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

// A controller harness, not a browser: no original files, navigation, or network.
class Element {
  children: Element[] = [];
  parentElement?: Element;
  value = "";
  textContent = "";
  checked = false;
  hidden = false;
  className = "";
  onclick?: () => void;
  events = new Map<string, () => void>();
  constructor(readonly tag: string) {}
  append(child: Element) {
    child.parentElement = this;
    this.children.push(child);
  }
  replaceChildren() {
    this.children = [];
  }
  addEventListener(event: string, callback: () => void) {
    this.events.set(event, callback);
  }
  change(value: string | boolean) {
    if (typeof value === "boolean") this.checked = value;
    else this.value = value;
    this.events.get("change")?.();
  }
  click() {
    this.onclick?.();
  }
  remove() {}
}

function form() {
  const mapping = {
    feature_id: "feature:invented-seat",
    status: "proposed",
    rationale: "Synthetic source meaning",
    reviewed_by: null,
    reviewed_at: null,
  };
  const payload = {
    manifest: {
      context_nodes: [
        {
          id: "vehicle:invented",
          type: "VehicleModel",
          label: "Invented",
          properties: { generation_code: "G70" },
        },
        {
          id: "feature:invented-seat",
          type: "Feature",
          label: "Invented seat",
          properties: { definition: "Invented definition" },
        },
      ],
      knowledge: {
        model_profiles: {
          "vehicle:invented": { segment: "unknown", curation_note: "Invented note" },
        },
        feature_keys: { "feature:invented-seat": "invented_seat" },
        vfc_mappings: { "Invented label": mapping },
        study_mappings: {},
        aspect_mappings: {},
      },
      pending_decisions: ["Review proposed canonical definition: feature:invented-seat"],
    },
    catalog: {
      model_id: null,
      country_codes: [],
      edition_note: null,
      publication_date: null,
      claims: [
        {
          page: 1,
          quote: "Invented original quote",
          statement: "Invented statement",
          feature_id: null,
          review_note: null,
          visual_checked: false,
          scope_checked: false,
          conditions_checked: false,
          status: "proposed",
          reviewed_by: null,
          reviewed_at: null,
          capability: { availability: "unknown", variant: null, conditions: [], notes: [] },
        },
      ],
    },
    availability: ["unknown", "optional"],
    pdf: btoa("Invented PDF bytes for the controller harness"),
  };
  const nodes = new Map<string, Element>();
  for (const id of [
    "payload",
    "reviewer",
    "message",
    "tabs",
    "definitions",
    "mappings",
    "catalog",
    "exports",
  ])
    nodes.set(id, new Element("div"));
  nodes.get("payload")!.textContent = JSON.stringify(payload);
  const document = {
    getElementById: (id: string) => nodes.get(id),
    createElement: (tag: string) => new Element(tag),
    createTextNode: (text: string) => Object.assign(new Element("text"), { textContent: text }),
    body: new Element("body"),
  };
  const html = readFileSync(
    new URL("../python/bmwow/knowledge/local_review.html", import.meta.url),
    "utf8",
  );
  const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1];
  assert.ok(script);
  const context = vm.createContext({
    document,
    Blob,
    URL: { createObjectURL: () => "blob:invented", revokeObjectURL() {} },
    atob,
    Uint8Array,
    structuredClone,
    Date,
    setTimeout: (callback: () => void) => callback(),
  });
  vm.runInContext(`${script}\nglobalThis.state = {manifest,catalog};`, context);
  const all = (node: Element): Element[] => [node, ...node.children.flatMap(all)];
  const field = (title: string, index = 0) => {
    const matches = [...nodes.values()]
      .flatMap(all)
      .filter(
        (node) =>
          node.tag === "label" &&
          (node.textContent === title ||
            node.children.some((child) => child.tag === "text" && child.textContent === title)),
      );
    assert.ok(matches[index], `Missing synthetic field: ${title}`);
    return matches[index].children.find((child) =>
      ["input", "textarea", "select"].includes(child.tag),
    )!;
  };
  return { field, nodes, state: context.state as typeof payload };
}

test("mapping review needs a reviewer and does not survive semantic edits", () => {
  const review = form();
  const decision = review.field("Your decision");
  decision.change("reviewed");
  assert.equal(review.state.manifest.knowledge.vfc_mappings["Invented label"].status, "proposed");
  assert.match(review.nodes.get("message")!.textContent, /reviewer/);
  review.nodes.get("reviewer")!.value = "synthetic-reviewer";
  decision.change("reviewed");
  const mapping = review.state.manifest.knowledge.vfc_mappings["Invented label"];
  assert.equal(mapping.reviewed_by, "synthetic-reviewer");
  assert.ok(mapping.reviewed_at);
  review.field("Reason for this mapping (source meaning and boundaries)").change("Changed meaning");
  assert.equal(mapping.status, "proposed");
  assert.equal(mapping.reviewed_by, null);
  decision.change("reviewed");
  review.field("Canonical definition").change("Changed canonical meaning");
  assert.equal(mapping.status, "proposed");
  assert.equal(decision.value, "proposed");
});

test("catalog review requires every source check and is invalidated by scope changes", () => {
  const review = form();
  review.nodes.get("reviewer")!.value = "synthetic-reviewer";
  review.field("Model covered by the catalog").change("vehicle:invented");
  review.field("Original country codes (comma separated)").change("DE");
  review.field("Edition and source scope note").change("Invented German edition");
  review.field("Canonical Feature", 1).change("feature:invented-seat");
  review.field("Review reason and source limitations").change("Invented source checks");
  const decision = review.field("Your decision", 1);
  const claim = review.state.catalog.claims[0];
  decision.change("reviewed");
  assert.equal(claim.status, "proposed");
  for (const title of [
    "Checked table columns and equipment symbols",
    "Checked model, country, variant, and edition",
    "Checked packages, dependencies, and footnotes",
  ])
    review.field(title).change(true);
  decision.change("reviewed");
  assert.equal(claim.status, "reviewed");
  assert.equal(claim.reviewed_by, "synthetic-reviewer");
  review.field("Original country codes (comma separated)").change("US");
  assert.equal(claim.status, "proposed");
  assert.equal(claim.reviewed_at, null);
  assert.equal(decision.value, "proposed");
  assert.equal(claim.visual_checked, false);
  assert.equal(claim.scope_checked, false);
  assert.equal(claim.conditions_checked, false);
});
