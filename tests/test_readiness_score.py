"""Pure, deterministic Readiness v0.3 contract tests."""

from datetime import date, timedelta
import math
import statistics

import pytest

from app.scores.readiness import (
    READINESS_MODEL_VERSION,
    readiness_v03,
    sample_mean_and_scale,
    sleep_debt_balance,
    weighted_seven_day,
)


DAY = date(2026, 10, 8)


def days_back(values):
    return {DAY - timedelta(days=offset): value for offset, value in values.items()}


def complete_inputs():
    hrv = days_back({offset: 60.0 + offset % 4 for offset in range(31)})
    rhr = days_back({offset: 61.0 + offset % 3 for offset in range(31)})
    sleep = days_back({offset: 420.0 for offset in range(7)})
    return hrv, rhr, sleep


def score(hrv=None, rhr=None, sleep=None, goal=420):
    original_hrv, original_rhr, original_sleep = complete_inputs()
    return readiness_v03(
        DAY,
        original_hrv if hrv is None else hrv,
        original_rhr if rhr is None else rhr,
        original_sleep if sleep is None else sleep,
        goal,
    )


def test_version_baseline_excludes_current_and_uses_calendar_window():
    assert READINESS_MODEL_VERSION == "readiness-emulator-v0.3"
    hrv, rhr, sleep = complete_inputs()
    hrv[DAY] = 200.0
    hrv[DAY - timedelta(days=31)] = 900.0
    result = score(hrv, rhr, sleep)
    assert result.hrv_baseline_days == 30
    assert result.components.hrv_current.baseline_mean == statistics.mean(
        hrv[DAY - timedelta(days=i)] for i in range(1, 31)
    )
    assert result.components.hrv_current.value == 200.0
    sparse = {DAY: 70.0, **days_back({i: 60.0 for i in range(17, 31)})}
    sparse.update(days_back({i: 100.0 for i in range(31, 47)}))
    result = score(sparse, rhr, sleep)
    assert result.hrv_baseline_days == 14
    assert result.components.hrv_current.baseline_mean == 60.0
    assert "insufficient_hrv_balance_window" in result.flags


def test_sample_sd_floor_and_favorable_z_directions():
    mean, sd, scale, floored = sample_mean_and_scale([60.0, 62.0], 1.0)
    assert mean == 61.0
    assert sd == pytest.approx(math.sqrt(2))
    assert scale == sd and floored is False
    assert sample_mean_and_scale([60.0] * 14, 1.0) == (60.0, 0.0, 1.0, True)
    hrv, rhr, sleep = complete_inputs()
    hrv[DAY] = 100.0
    rhr[DAY] = 40.0
    result = score(hrv, rhr, sleep)
    assert result.components.hrv_current.z > 0
    assert result.components.rhr_current.z > 0
    assert result.components.hrv_current.positive_term > 0
    assert result.components.rhr_current.positive_term > 0


def test_negative_dead_band_is_one_sided():
    hrv, rhr, sleep = complete_inputs()
    hrv_baseline = [hrv[DAY - timedelta(days=i)] for i in range(1, 31)]
    mean, _, scale, _ = sample_mean_and_scale(hrv_baseline, 1.0)
    hrv[DAY] = mean - 0.9 * scale
    mild = score(hrv, rhr, sleep)
    assert mild.components.hrv_current.negative_term == 0
    hrv[DAY] = mean - 1.9 * scale
    severe = score(hrv, rhr, sleep)
    assert severe.components.hrv_current.negative_term == pytest.approx(0.9)


def test_hrv_balance_uses_date_weights_and_never_shifts_missing_dates():
    values = days_back({i: float(10 * (i + 1)) for i in range(7)})
    weighted, count, partial = weighted_seven_day(values, DAY)
    assert weighted == pytest.approx(
        sum((0.8 ** i) * values[DAY - timedelta(days=i)] for i in range(7))
        / sum(0.8 ** i for i in range(7))
    )
    assert count == 7 and partial is False
    del values[DAY - timedelta(days=2)]
    weighted, count, partial = weighted_seven_day(values, DAY)
    assert weighted == pytest.approx(
        sum((0.8 ** i) * values[DAY - timedelta(days=i)] for i in (0, 1, 3, 4, 5, 6))
        / sum(0.8 ** i for i in (0, 1, 3, 4, 5, 6))
    )
    assert count == 6 and partial is True
    del values[DAY - timedelta(days=1)]
    assert weighted_seven_day(values, DAY)[1:] == (5, True)
    del values[DAY - timedelta(days=3)]
    assert weighted_seven_day(values, DAY) == (None, 4, False)


def test_hrv_balance_requires_current_and_applies_only_negative_penalty():
    hrv, rhr, sleep = complete_inputs()
    hrv[DAY] = 200.0
    assert score(hrv, rhr, sleep).components.hrv_balance_7d.penalty_term == 0
    del hrv[DAY]
    result = score(hrv, rhr, sleep)
    assert result.calculated_score is None
    assert "missing_current_hrv" in result.flags


def test_sleep_debt_extra_sleep_partial_windows_and_exponential_balance():
    sleep = days_back({i: 450.0 for i in range(7)})
    assert sleep_debt_balance(sleep, DAY, 420) == (0.0, 100.0, 7, False)
    sleep[DAY] = 210.0
    debt, balance, nights, partial = sleep_debt_balance(sleep, DAY, 420)
    assert (debt, nights, partial) == (210.0, 7, False)
    assert balance == pytest.approx(100 * math.exp(-210 / 420), rel=1e-12)
    del sleep[DAY - timedelta(days=2)]
    debt, balance, nights, partial = sleep_debt_balance(sleep, DAY, 420)
    assert (debt, nights, partial) == (245.0, 6, True)
    assert balance == pytest.approx(100 * math.exp(-245 / 420), rel=1e-12)
    del sleep[DAY - timedelta(days=3)]
    assert sleep_debt_balance(sleep, DAY, 420)[2:] == (5, True)
    del sleep[DAY - timedelta(days=4)]
    assert sleep_debt_balance(sleep, DAY, 420) == (None, None, 4, False)


def test_exact_equation_clamp_and_half_up_rounding():
    result = score()
    c = result.components
    expected = (
        53.81
        + 16.83 * c.hrv_current.positive_term
        - 18.57 * c.hrv_current.negative_term
        + 9.85 * c.rhr_current.positive_term
        - 38.21 * c.rhr_current.negative_term
        - 10.24 * c.hrv_balance_7d.penalty_term
        + 0.05 * c.sleep_balance_7d.balance
    )
    assert result.calculated_raw_score == pytest.approx(min(100, max(1, expected)))
    assert result.calculated_score == math.floor(result.calculated_raw_score + 0.5)
    assert 1 <= result.calculated_score <= 100
    assert score({**complete_inputs()[0], DAY: 1000.0}).calculated_score == 100
    assert score(rhr={**complete_inputs()[1], DAY: 1000.0}).calculated_score == 1


def test_half_up_boundary_without_bankers_rounding():
    from app.scores.readiness import round_half_up_clamped

    assert round_half_up_clamped(50.5) == (51, 50.5)
    assert round_half_up_clamped(-100) == (1, 1.0)
    assert round_half_up_clamped(200) == (100, 100.0)


def test_monotonic_model_effects():
    hrv, rhr, sleep = complete_inputs()
    base = score(hrv, rhr, sleep)
    assert score({**hrv, DAY: hrv[DAY] + 1}, rhr, sleep).calculated_score >= base.calculated_score
    assert score(hrv, {**rhr, DAY: rhr[DAY] - 1}, sleep).calculated_score >= base.calculated_score
    assert score(hrv, rhr, {**sleep, DAY: 300.0}).calculated_score <= base.calculated_score
    assert score({**hrv, DAY - timedelta(days=1): 30.0}, rhr, sleep).calculated_score <= base.calculated_score


def test_coverage_invalid_values_and_flat_baseline_are_finite():
    hrv, rhr, sleep = complete_inputs()
    hrv = {day: 60.0 for day in hrv}
    rhr = {day: 60.0 for day in rhr}
    result = score(hrv, rhr, sleep)
    assert "hrv_sd_floor_applied" in result.flags
    assert "rhr_sd_floor_applied" in result.flags
    assert math.isfinite(result.calculated_raw_score)
    hrv[DAY] = float("nan")
    rhr[DAY] = -1.0
    sleep[DAY] = float("inf")
    result = score(hrv, rhr, sleep)
    assert result.calculated_score is None
    assert {"missing_current_hrv", "missing_current_rhr", "partial_sleep_window"} <= set(result.flags)
    assert result.components.hrv_current.value is None
    assert result.components.rhr_current.value is None


def test_insufficient_baselines_balance_sleep_and_goal():
    hrv, rhr, sleep = complete_inputs()
    for offset in range(14, 31):
        del hrv[DAY - timedelta(days=offset)]
        del rhr[DAY - timedelta(days=offset)]
    result = score(hrv, rhr, sleep)
    assert result.hrv_baseline_days == result.rhr_baseline_days == 13
    assert {"insufficient_hrv_baseline", "insufficient_rhr_baseline"} <= set(result.flags)
    assert result.calculation_insufficient_data is True
    hrv[DAY - timedelta(days=14)] = 60.0
    rhr[DAY - timedelta(days=14)] = 61.0
    assert score(hrv, rhr, sleep).calculated_score is not None
    assert "invalid_sleep_goal" in score(hrv, rhr, sleep, 0).flags
    partial = score(hrv, rhr, {k: v for k, v in sleep.items() if k != DAY})
    assert "partial_sleep_window" in partial.flags
    assert partial.calculated_score is not None
