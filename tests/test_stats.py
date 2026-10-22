import pytest

from netguardx.eval.stats import mean_ci, t95


def test_mean_and_interval_match_a_hand_calculation():
    m, half = mean_ci([10.0, 12.0, 14.0])  # mean 12, sd 2, n 3, t(2) = 4.303
    assert m == 12 and half == pytest.approx(4.303 * 2 / 3 ** 0.5)


def test_one_value_has_no_interval_and_none_is_an_error():
    assert mean_ci([5.0]) == (5.0, None)
    with pytest.raises(ValueError):
        mean_ci([])


def test_t_values_shrink_towards_the_normal_value():
    assert t95(1) > t95(4) > t95(29) > t95(100) == 1.96
    assert t95(22) == t95(20)  # untabulated: the next smaller df, never narrower
