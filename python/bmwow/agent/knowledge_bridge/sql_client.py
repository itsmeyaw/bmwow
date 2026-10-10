"""v1 sales entry point; the backing repository can later be Neon."""

from .runtime import get_service


def sales_volume(
    models: list[str],
    markets: list[str] | None = None,
    period_from: str | None = None,
    period_to: str | None = None,
):
    return get_service().sales_volume(models, markets, period_from, period_to)
