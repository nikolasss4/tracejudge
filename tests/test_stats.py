import pytest

from tracejudge.stats import fisher_exact, pass_at_k, pass_hat_k, percentile, wilson_interval


def test_pass_at_k() -> None:
    assert pass_at_k(3, 0, 3) == 0
    assert pass_at_k(3, 1, 3) == 1
    assert pass_at_k(3, 1, 1) == pytest.approx(1 / 3)
    assert pass_at_k(5, 2, 2) == pytest.approx(1 - 3 / 10)


def test_pass_hat_k() -> None:
    assert pass_hat_k(3, 3, 3) == 1
    assert pass_hat_k(3, 2, 3) == 0
    assert pass_hat_k(4, 3, 2) == pytest.approx(3 / 6)


def test_fisher_exact_matches_scipy_reference() -> None:
    # Values cross-checked against scipy.stats.fisher_exact.
    assert fisher_exact(8, 2, 1, 5) == pytest.approx(0.0349650, rel=1e-5)
    assert fisher_exact(3, 1, 1, 3) == pytest.approx(0.4857142857, rel=1e-6)
    assert fisher_exact(5, 5, 5, 5) == pytest.approx(1.0)


def test_wilson_and_percentile() -> None:
    lo, hi = wilson_interval(9, 10)
    assert lo == pytest.approx(0.5958, abs=1e-3) and hi == pytest.approx(0.9821, abs=1e-3)
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([], 95) == 0
