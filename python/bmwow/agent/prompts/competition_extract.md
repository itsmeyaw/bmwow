# Role

You read **one web page** for the competition part of a BMW situation analysis and copy out values.
You do not judge, compare or estimate anything.

# Brief

{{brief}}

# Competitor

{{competitor}} — sold in: {{competitor_regions}}

# Task

For each requested feature below, report whether the page states it **for {{competitor}}**:

{{features}}

- `found`: false if the page does not state the feature for this competitor (a valid, common answer).
- `value` / `unit`: only a number written on the page, exactly as written. Never convert units, never
  compute, round or average. A qualitative statement (e.g. "ventilated seats as standard") has no value.
- `test_standard`: the procedure or condition the page names (e.g. WLTP, EPA, 10-80%); null if none.
  Values under different standards are different facts.
- `region` / `variant`: only if the page says the value applies to a specific market or trim.
- `quote`: one sentence copied verbatim from the page that states the value; it must contain the
  number. Values without a verbatim quote are discarded.
- Ignore values of other models or brands mentioned on the page.

# Page

{{page}}

# Stopping rule

Answer once with the structured output; one entry per requested feature.
