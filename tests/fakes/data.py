"""Synthetic, clearly fake data for every §4 contract. Deterministic (seeded)."""

from __future__ import annotations

import random
from datetime import date

from src.agent.tools.knowledge import AttributeValue, DocChunk, FeedbackItem, ModelNode, SalesRow

SEGMENT = "Premium mid-size sedan"
REF_CODE = "TEST01"  # the fake reference model
CN_ONLY_CODE = "TEST02"  # a registry model that only has data for CN
REFERENCE = "Sedan X (fake)"

# Fake registry (served through the optional list_supported_models / list_regions contracts).
SUPPORTED_MODELS = [
    {"model_code": REF_CODE, "name": REFERENCE, "regions": ["EU", "CN"]},
    {"model_code": CN_ONLY_CODE, "name": "Sedan X Long (fake)", "regions": ["CN"]},
]
REGIONS = {
    "EU": {"markets": ["DE", "FR"], "search": {"country": "de", "lang": "en"}},
    "CN": {"markets": ["CN"], "search": {"country": "cn", "lang": "zh"}},
}


def _attrs(prefix: str, values: list[tuple[str, float | str, str | None, str]], as_of: date | None = None):
    return [AttributeValue(node_id=f"{prefix}-{a}", attribute=a, value=v, unit=u, source_note=n, as_of=as_of)
            for a, v, u, n in values]


def models() -> dict[str, ModelNode]:
    bmw = dict(brand="BMW (fake)", segment=SEGMENT)
    out = [
        ModelNode(node_id="m-test01", model_code=REF_CODE, name=REFERENCE, powertrain="BEV", regions=["EU", "CN"],
                  attributes=_attrs("av-test01", [
                      ("real_world_range", 455, "km", "WLTP"),
                      ("fast_charging", 32, "min", "10-80%"),
                      ("efficiency", 17.2, "kWh/100km", "WLTP combined"),
                      ("rear_space", 905, "mm", "rear legroom"),
                      ("seat_ventilation", "not available", None, ""),
                      ("physical_controls", "few physical buttons", None, ""),
                  ], date(2025, 6, 1)), **bmw),
        ModelNode(node_id="m-test02", model_code=CN_ONLY_CODE, name="Sedan X Long (fake)", powertrain="BEV",
                  regions=["CN"], attributes=_attrs("av-test02", [
                      ("rear_space", 1010, "mm", "rear legroom"),
                      ("seat_ventilation", "standard", None, ""),
                  ], date(2025, 6, 1)), **bmw),
        ModelNode(node_id="m-touring-x", model_code="TEST03", name="Touring X (fake)", powertrain="BEV",
                  regions=["EU"], attributes=_attrs("av-touring-x", [
                      ("real_world_range", 430, "km", "WLTP"),
                      ("flexible_storage", 570, "l", "boot volume"),
                  ], date(2025, 6, 1)), **bmw),
        ModelNode(node_id="m-coupe-x", model_code="TEST04", name="Gran Coupe X (fake)", powertrain="ICE",
                  regions=["EU", "CN"], attributes=_attrs("av-coupe-x", [
                      ("dynamic_handling", "sport suspension standard", None, ""),
                      ("rear_space", 860, "mm", "rear legroom"),
                  ], date(2025, 6, 1)), **bmw),
        # competitors: EU = A, B, D; CN = A, C
        ModelNode(node_id="c-a", name="Competitor A Sedan", brand="Competitor A", segment=SEGMENT, powertrain="BEV",
                  regions=["EU", "CN"], attributes=_attrs("av-c-a", [
                      ("real_world_range", 520, "km", "WLTP"),
                      ("fast_charging", 28, "min", "10-80%"),
                  ], date(2025, 9, 1))),
        ModelNode(node_id="c-b", name="Competitor B Sedan", brand="Competitor B", segment=SEGMENT, powertrain="BEV",
                  regions=["EU"], attributes=_attrs("av-c-b", [
                      ("real_world_range", 480, "km", "WLTP"),
                      ("seat_ventilation", "optional", None, ""),
                  ], date(2025, 9, 1))),
        ModelNode(node_id="c-c", name="Competitor C Sedan", brand="Competitor C", segment=SEGMENT, powertrain="BEV",
                  regions=["CN"], attributes=_attrs("av-c-c", [("real_world_range", 400, "km", "NEDC")],
                                                    date(2019, 1, 1))),
        ModelNode(node_id="c-d", name="Competitor D Sedan", brand="Competitor D", segment=SEGMENT, powertrain="PHEV",
                  regions=["EU"], attributes=_attrs("av-c-d", [("affordable", 52900, "EUR", "base price DE")],
                                                    date(2025, 3, 1))),
    ]
    return {m.node_id: m for m in out}


PORTFOLIO_IDS = ["m-test01", "m-test02", "m-touring-x", "m-coupe-x"]
COMPETITOR_IDS = ["c-a", "c-b", "c-c", "c-d"]
EU_ONLY_COMPETITORS = ["Competitor B Sedan", "Competitor D Sedan"]


def sales() -> list[SalesRow]:
    """Keyed by model code; each model only in the markets of its regions."""
    base = {REF_CODE: 30000, CN_ONLY_CODE: 9000, "TEST03": 12000, "TEST04": 8000}
    growth = {REF_CODE: 0.92, CN_ONLY_CODE: 1.20, "TEST03": 1.05, "TEST04": 0.97}
    mix = {REF_CODE: {"DE": 0.4, "FR": 0.25, "CN": 0.35}, CN_ONLY_CODE: {"CN": 1.0},
           "TEST03": {"DE": 0.6, "FR": 0.4}, "TEST04": {"DE": 0.5, "FR": 0.2, "CN": 0.3}}
    rows = []
    for model, units in base.items():
        for market, m_share in mix[model].items():
            rows.append(SalesRow(model=model, market=market, period="2023", units=int(units * m_share)))
            rows.append(SalesRow(model=model, market=market, period="2024", units=int(units * m_share * growth[model])))
    return rows


# Planted feedback themes: (theme, attribute, polarity, phrases). seat_ventilation is only in CN.
THEMES = [
    ("winter_range", "real_world_range", "negative",
     ["range drops in winter", "cold weather kills the battery range", "lost a third of range when freezing",
      "winter range is disappointing", "battery range shrinks in the cold"]),
    ("laggy_infotainment", "reliable_software", "negative",
     ["infotainment screen is laggy", "the software freezes and reboots", "touchscreen lag is annoying",
      "infotainment crashed again", "screen is slow to respond"]),
    ("seat_ventilation", "seat_ventilation", "demand",
     ["wish the seats had ventilation", "need cooled seats for hot summers", "ventilated seats should be available",
      "seats get sweaty in summer heat", "please add seat cooling"]),
    ("slow_charging", "fast_charging", "negative",
     ["charging is slow at fast chargers", "dc charging takes too long", "charging speed tapers early",
      "waiting forever at the charger", "charge curve is too flat"]),
    ("rear_space", "rear_space", "negative",
     ["rear seats are cramped", "not enough legroom in the back", "tall passengers hate the rear bench",
      "back seat knee room is tight", "kids complain about rear space"]),
    ("handling", "dynamic_handling", "positive",
     ["handling is precise and fun", "steering feels sharp in corners", "best driving dynamics in its class",
      "chassis balance is superb", "loves twisty roads"]),
]
FILLER = ["honestly", "overall", "after six months", "on my daily commute", "as a long time owner", "this year",
          "compared to my old car", "every week", "on long trips", "in the city"]
CN_ONLY_THEME = "seat_ventilation"
PLACES = ["munich", "lyon", "shanghai", "hamburg", "paris", "shenzhen", "cologne", "lille", "chengdu",
          "leipzig", "nantes", "wuhan", "dresden", "bordeaux", "nanjing", "bremen", "toulouse", "xiamen"]
NOISE = ["the paint color is nice", "dealer coffee was good", "delivery took eight weeks",
         "the key fob battery died", "parking garage at the dealer was full", "brochure arrived late"]


def feedback(seed: int = 7, per_theme: int = 24) -> list[FeedbackItem]:
    rng = random.Random(seed)
    items: list[FeedbackItem] = []
    channels = ["dealer_survey", "app_store", "forum", "social"]
    markets = ["DE", "FR", "CN"]
    n = 0
    for theme, _attr, _pol, phrases in THEMES:
        for _ in range(per_theme):
            n += 1
            parts = rng.sample(phrases, 2) + [f"{rng.choice(FILLER)} near {rng.choice(PLACES)}"]
            rng.shuffle(parts)
            items.append(FeedbackItem(item_id=f"fb-{n:04d}", text=". ".join(parts).capitalize() + ".",
                                      channel=rng.choice(channels),
                                      market="CN" if theme == CN_ONLY_THEME else rng.choice(markets),
                                      date=date(2025, rng.randint(1, 12), rng.randint(1, 28)),
                                      rating=float(rng.randint(1, 5)), model=REF_CODE))
    for text in NOISE:
        n += 1
        items.append(FeedbackItem(item_id=f"fb-{n:04d}", text=text.capitalize() + ".", channel="forum",
                                  market=rng.choice(markets), date=date(2025, 5, 1), rating=3.0, model=REF_CODE))
    # exact duplicates (reposts)
    for src in items[:5]:
        n += 1
        items.append(src.model_copy(update={"item_id": f"fb-{n:04d}", "text": src.text.upper()}))
    return items




def theme_for(text: str) -> str | None:
    low = text.lower()
    for theme, _attr, _pol, phrases in THEMES:
        if any(p in low for p in phrases):
            return theme
    return None


def documents() -> list[tuple[str, DocChunk]]:
    """(kind, chunk) pairs."""
    return [
        ("study", DocChunk(node_id="doc-mcs-1", doc_title="Fake Study 1: Charging Infrastructure Outlook",
                           text="Megawatt-class and 400 kW DC chargers are expanding along European highways. "
                                "The fake study expects 35 percent of new highway chargers to exceed 300 kW by 2027. "
                                "Customers increasingly expect a 10-80% charge in under 20 minutes.",
                           url=None, published=date(2025, 4, 1), regions=["EU"])),
        ("study", DocChunk(node_id="doc-ota-1", doc_title="Fake Study 2: Software-Defined Vehicles",
                           text="Software-defined vehicle architectures enable frequent over-the-air updates. "
                                "In the fake survey, 62 percent of premium buyers rate reliable software as a purchase "
                                "criterion. Laggy infotainment is the most cited digital complaint.",
                           url=None, published=date(2025, 2, 1))),
        ("report", DocChunk(node_id="doc-reg-1", doc_title="Fake Report 3: Regulation Watch",
                            text="New safety assessment protocols from 2026 reward physical controls for core functions "
                                 "such as indicators and hazard lights. The EU battery passport becomes mandatory "
                                 "for EV batteries from February 2027.",
                            url=None, published=date(2025, 1, 15), regions=["EU"])),
        ("study", DocChunk(node_id="doc-cool-1", doc_title="Fake Study 4: Comfort Features in Warm Markets",
                           text="Rising summer temperatures increase demand for ventilated seats. In the fake study, "
                                "ventilated seats moved from a luxury option to an expected feature for 48 percent "
                                "of buyers in warm markets.",
                           url=None, published=date(2025, 7, 1), regions=["CN"])),
        ("report", DocChunk(node_id="doc-sus-1", doc_title="Fake Report 5: Sustainable Materials",
                            text="Premium buyers increasingly ask for recycled and vegan interior materials. "
                                 "Sustainability is becoming a brand-level expectation rather than a niche option.",
                            url=None, published=date(2025, 3, 1))),
    ]


WEB_PAGES = {
    "https://example.com/competitor-a-sedan/specs": (
        "Competitor A Sedan – technical data (fake)",
        "# Competitor A Sedan technical data\n\nThe Competitor A Sedan offers ventilated front seats as standard.\n\n"
        "Infotainment: 14.9 inch central display with physical climate buttons.\n\n"
        "Rear legroom: 940 mm.",
    ),
    "https://example.com/competitor-b-sedan/review": (
        "Competitor B Sedan review (fake)",
        "# Competitor B Sedan review\n\nIn our test the Competitor B Sedan charged from 10-80% in 22 minutes.\n\n"
        "The infotainment responded quickly and the rear legroom of 915 mm is class average.",
    ),
    "https://example.com/competitor-c-sedan/specs": (
        "Competitor C Sedan specifications (fake)",
        "# Competitor C Sedan specifications\n\nUpdated model year: WLTP range of 575 km.\n\n"
        "DC fast charging 10-80% in 30 minutes. Ventilated seats optional.",
    ),
    "https://example.com/competitor-d-sedan/specs": (
        "Competitor D Sedan specifications (fake)",
        "# Competitor D Sedan specifications\n\nElectric range of 85 km (WLTP) as a plug-in hybrid.\n\n"
        "Rear legroom 925 mm.",
    ),
    "https://example.com/news/megawatt-charging": (
        "Megawatt charging rollout (fake news)",
        "# Megawatt charging rollout\n\nOperators announced 1,200 new high-power charging points for 2026.\n\n"
        "Charging sessions under 15 minutes are becoming a marketing benchmark.",
    ),
}
