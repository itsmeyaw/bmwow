import pytest

from bmwow.agent.stats import (
    distribution,
    is_thin,
    rank_position,
    relative_difference,
    two_proportion_p,
    wilson_interval,
)


def test_wilson_interval_known_values():
    low, high = wilson_interval(12, 82)
    assert low == pytest.approx(0.0855, abs=5e-4) and high == pytest.approx(0.2385, abs=5e-4)
    assert wilson_interval(0, 50)[0] == 0.0 and wilson_interval(0, 50)[1] > 0
    assert wilson_interval(50, 50)[1] == 1.0
    assert wilson_interval(0, 0) == (0.0, 0.0)
    with pytest.raises(ValueError):
        wilson_interval(5, 3)


def test_two_proportion_test():
    assert two_proportion_p(12, 82, 29, 1593) < 1e-6  # 14.6% vs 1.8%
    assert two_proportion_p(10, 100, 10, 100) == pytest.approx(1.0)
    assert two_proportion_p(0, 10, 0, 10) is None and two_proportion_p(1, 0, 1, 10) is None


def test_thin_and_distribution_helpers():
    assert is_thin(4, 100, 30, 5) and is_thin(10, 20, 30, 5) and not is_thin(5, 30, 30, 5)
    d = distribution([520, 400, 480, 575])
    assert (d.n, d.minimum, d.median, d.maximum) == (4, 400, 500, 575)
    assert distribution([]) is None
    assert rank_position(455, [520, 480, 400], higher_is_better=True) == (3, 4)
    assert rank_position(22, [28, 30], higher_is_better=False) == (1, 3)
    assert relative_difference(455, 520) == pytest.approx(-0.125)
    assert relative_difference(1, 0) is None
