## Rules (apply to every finding)

- **One claim per finding.** Each `claim` is one sentence that states exactly one fact about one subject
  and one attribute. Split compound statements into several findings.
- **Taxonomy.** Set `attribute` to one taxonomy key from the list below. If nothing fits, use
  `unmapped:<snake_case_name>`; never force a poor fit.
- **Citations.** Every finding cites at least one source id that was shown to you in this conversation
  (`kg:…`, `sql:…`, `web:…`, `fb:…` or a temporary key such as `P3`). Never cite an id you did not see,
  and never make up a URL or id. Findings with unknown ids are discarded.
- **Evidence.** `evidence_quote` (when the schema has it) is copied verbatim from the cited source text,
  10–300 characters, and contains every number the claim uses.
- **Numbers.** Fill `value`/`unit` only with a number that is written in the cited source. Never estimate,
  convert, average or round. If the source has no number, leave `value` empty and keep the claim qualitative.
- **Confidence.** `high` = official/manufacturer or structured data; `medium` = reputable secondary
  source; `low` = single anecdotal or unclear source.
- **Regions.** Work only on the regions in the brief. A finding that holds only in some regions
  (prices, spec variants, availability, regulation, local preferences) names the region in the claim and
  in `qualifier` (e.g. "2025 CN"). Findings that hold everywhere stay unqualified.
- If the evidence is thin, return fewer findings. An empty list is a valid answer.

## Taxonomy

{{taxonomy}}
