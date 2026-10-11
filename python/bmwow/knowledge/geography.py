"""Explicit country grouping for feedback reads; original country scope is retained."""

from collections.abc import Iterable

# ISO 3166-1 alpha-2 codes for the 27 EU members, verified on 2026-10-10.
# https://european-union.europa.eu/easy-read_en
EU_COUNTRY_CODES = (
    "AT",
    "BE",
    "BG",
    "CY",
    "CZ",
    "DE",
    "DK",
    "EE",
    "ES",
    "FI",
    "FR",
    "GR",
    "HR",
    "HU",
    "IE",
    "IT",
    "LT",
    "LU",
    "LV",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SE",
    "SI",
    "SK",
)


def feedback_region(country: str) -> str:
    code = country.strip().upper()
    return "EU" if code in EU_COUNTRY_CODES else code


def feedback_country_markets(markets: Iterable[str]) -> list[str]:
    """Expand the EU query alias and deduplicate mixed region/country selections."""
    countries = []
    for market in markets:
        code = market.strip().upper()
        countries.extend(EU_COUNTRY_CODES if code == "EU" else (code,))
    return list(dict.fromkeys(countries))


def feedback_region_markets(countries: Iterable[str]) -> dict[str, list[str]]:
    """Group observed country coverage; never advertise unobserved member countries."""
    regions: dict[str, list[str]] = {}
    for country in sorted({value.strip().upper() for value in countries if value.strip()}):
        regions.setdefault(feedback_region(country), []).append(country)
    return regions
