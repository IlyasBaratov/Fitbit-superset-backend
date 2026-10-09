"""Pure, date-based experimental Readiness Score v0.3 calculation."""

from dataclasses import dataclass
from datetime import date, timedelta
import math
import statistics
from typing import Mapping


READINESS_MODEL_VERSION = "readiness-emulator-v0.3"

# Calendar windows, coverage requirements, and numerical guards (not fitted).
HRV_BASELINE_DAYS = 30
RHR_BASELINE_DAYS = 30
MIN_BASELINE_VALUES = 14
BALANCE_DAYS = 7
MIN_BALANCE_VALUES = 5
RECENCY_DECAY = 0.8
HRV_SD_FLOOR_MS = 1.0
RHR_SD_FLOOR_BPM = 1.0

# Owner-approved fitted v0.3 equation constants; changing one requires a new version.
INTERCEPT = 53.81
HRV_POS_COEF = 16.83
HRV_NEG_COEF = -18.57
RHR_POS_COEF = 9.85
RHR_NEG_COEF = -38.21
HRV_BALANCE_NEG_COEF = -10.24
SLEEP_BALANCE_COEF = 0.05


@dataclass(frozen=True)
class MetricComponent:
    value: float | None = None
    baseline_mean: float | None = None
    baseline_sd: float | None = None
    scale: float | None = None
    z: float | None = None
    positive_term: float | None = None
    negative_term: float | None = None
    days_used: int = 0


@dataclass(frozen=True)
class BalanceComponent:
    value: float | None = None
    z: float | None = None
    penalty_term: float | None = None
    days_used: int = 0
    decay: float = RECENCY_DECAY


@dataclass(frozen=True)
class SleepComponent:
    goal_minutes: float | None = None
    debt_minutes: float | None = None
    balance: float | None = None
    nights_used: int = 0


@dataclass(frozen=True)
class ReadinessComponents:
    hrv_current: MetricComponent
    rhr_current: MetricComponent
    hrv_balance_7d: BalanceComponent
    sleep_balance_7d: SleepComponent


@dataclass(frozen=True)
class ReadinessResult:
    calculated_score: int | None
    calculated_raw_score: float | None
    calculation_insufficient_data: bool
    hrv_baseline_days: int
    rhr_baseline_days: int
    components: ReadinessComponents
    flags: tuple[str, ...]


def _number(value: object, *, positive: bool = False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(number) or (number <= 0 if positive else number < 0):
        return None
    return number


def sample_mean_and_scale(values, floor: float) -> tuple[float, float, float, bool]:
    """Mean, sample SD, guarded scale, and whether the SD floor was applied."""
    if len(values) < 2 or not math.isfinite(floor) or floor <= 0:
        raise ValueError("A sample and a positive SD floor are required")
    if any(_number(value, positive=True) is None for value in values):
        raise ValueError("Baseline values must be finite and positive")
    mean = statistics.fmean(values)
    sd = statistics.stdev(values)
    if not math.isfinite(mean) or not math.isfinite(sd):
        raise ValueError("Baseline statistics must be finite")
    return mean, sd, max(sd, floor), sd < floor


def weighted_seven_day(
    values_by_date: Mapping[date, float], day: date, decay: float = RECENCY_DECAY
) -> tuple[float | None, int, bool]:
    """Date-specific weights remain fixed when an intervening HRV date is absent."""
    if not math.isfinite(decay) or not 0 < decay <= 1:
        raise ValueError("Decay must be finite and in (0, 1]")
    available = [
        (decay ** offset, value)
        for offset in range(BALANCE_DAYS)
        if (value := _number(values_by_date.get(day - timedelta(days=offset)), positive=True))
        is not None
    ]
    count = len(available)
    if count < MIN_BALANCE_VALUES or _number(values_by_date.get(day), positive=True) is None:
        return None, count, False
    weighted = sum(weight * value for weight, value in available) / sum(
        weight for weight, _ in available
    )
    return (weighted if math.isfinite(weighted) else None), count, count < BALANCE_DAYS


def sleep_debt_balance(
    sleep_minutes_by_wake_date: Mapping[date, float], day: date, goal_minutes: float
) -> tuple[float | None, float | None, int, bool]:
    """Extrapolate observed nightly debt to seven nights when coverage is partial."""
    observed = [
        value
        for offset in range(BALANCE_DAYS)
        if (value := _number(sleep_minutes_by_wake_date.get(day - timedelta(days=offset))))
        is not None
    ]
    count = len(observed)
    partial = MIN_BALANCE_VALUES <= count < BALANCE_DAYS
    goal = _number(goal_minutes, positive=True)
    if count < MIN_BALANCE_VALUES or goal is None:
        return None, None, count, False
    debt = sum(max(0.0, goal - value) for value in observed) * BALANCE_DAYS / count
    balance = 100.0 * math.exp(-debt / goal)
    if not math.isfinite(debt) or not math.isfinite(balance):
        return None, None, count, partial
    return debt, balance, count, partial


def round_half_up_clamped(raw: float) -> tuple[int, float]:
    """The v0.3 score never uses Python's ties-to-even round()."""
    if not math.isfinite(raw):
        raise ValueError("Readiness raw score must be finite")
    clamped = min(100.0, max(1.0, raw))
    return math.floor(clamped + 0.5), clamped


def _metric(
    current: float | None, values: list[float], floor: float, reverse: bool
) -> tuple[MetricComponent, bool]:
    count = len(values)
    if count < MIN_BASELINE_VALUES:
        return MetricComponent(value=current, days_used=count), False
    try:
        mean, sd, scale, floored = sample_mean_and_scale(values, floor)
        z = ((mean - current) if reverse else (current - mean)) / scale if current is not None else None
        if z is not None and not math.isfinite(z):
            z = None
        positive = max(z, 0.0) if z is not None else None
        negative = max(-z - 1.0, 0.0) if z is not None else None
        return MetricComponent(current, mean, sd, scale, z, positive, negative, count), floored
    except (OverflowError, ValueError, statistics.StatisticsError):
        return MetricComponent(value=current, days_used=count), False


def readiness_v03(
    day: date,
    hrv_by_date: Mapping[date, float],
    rhr_by_date: Mapping[date, float],
    sleep_minutes_by_wake_date: Mapping[date, float],
    goal_minutes: float,
) -> ReadinessResult:
    """Calculate one day from real input maps; observed labels are never inputs."""
    flags: list[str] = []
    current_hrv = _number(hrv_by_date.get(day), positive=True)
    current_rhr = _number(rhr_by_date.get(day), positive=True)
    if current_hrv is None:
        flags.append("missing_current_hrv")
    if current_rhr is None:
        flags.append("missing_current_rhr")

    hrv_baseline = [
        value
        for offset in range(1, HRV_BASELINE_DAYS + 1)
        if (value := _number(hrv_by_date.get(day - timedelta(days=offset)), positive=True))
        is not None
    ]
    rhr_baseline = [
        value
        for offset in range(1, RHR_BASELINE_DAYS + 1)
        if (value := _number(rhr_by_date.get(day - timedelta(days=offset)), positive=True))
        is not None
    ]
    hrv, hrv_floored = _metric(current_hrv, hrv_baseline, HRV_SD_FLOOR_MS, False)
    rhr, rhr_floored = _metric(current_rhr, rhr_baseline, RHR_SD_FLOOR_BPM, True)
    if hrv.baseline_mean is None:
        flags.append("insufficient_hrv_baseline")
    if rhr.baseline_mean is None:
        flags.append("insufficient_rhr_baseline")
    if hrv_floored:
        flags.append("hrv_sd_floor_applied")
    if rhr_floored:
        flags.append("rhr_sd_floor_applied")

    hrv_mean, hrv_count, hrv_partial = weighted_seven_day(hrv_by_date, day)
    hrv_balance = BalanceComponent(value=hrv_mean, days_used=hrv_count)
    if hrv_mean is None:
        flags.append("insufficient_hrv_balance_window")
    else:
        if hrv_partial:
            flags.append("partial_hrv_balance_window")
        if hrv.baseline_mean is not None and hrv.scale is not None:
            z_balance = (hrv_mean - hrv.baseline_mean) / hrv.scale
            if math.isfinite(z_balance):
                hrv_balance = BalanceComponent(
                    value=hrv_mean, z=z_balance, penalty_term=max(-z_balance, 0.0),
                    days_used=hrv_count,
                )

    goal = _number(goal_minutes, positive=True)
    if goal is None:
        flags.append("invalid_sleep_goal")
    debt, balance, sleep_count, sleep_partial = sleep_debt_balance(
        sleep_minutes_by_wake_date, day, goal_minutes
    )
    sleep_component = SleepComponent(
        goal_minutes=_number(goal_minutes), debt_minutes=debt,
        balance=balance, nights_used=sleep_count,
    )
    if balance is None:
        flags.append("insufficient_sleep_window")
    elif sleep_partial:
        flags.append("partial_sleep_window")

    components = ReadinessComponents(hrv, rhr, hrv_balance, sleep_component)
    terms = (
        hrv.positive_term, hrv.negative_term, rhr.positive_term, rhr.negative_term,
        hrv_balance.penalty_term, balance,
    )
    if any(value is None for value in terms) or goal is None:
        return ReadinessResult(
            None, None, True, len(hrv_baseline), len(rhr_baseline), components, tuple(flags)
        )
    h_pos, h_neg, r_pos, r_neg, b_h, sleep_balance = terms
    raw = (
        INTERCEPT + HRV_POS_COEF * h_pos + HRV_NEG_COEF * h_neg
        + RHR_POS_COEF * r_pos + RHR_NEG_COEF * r_neg
        + HRV_BALANCE_NEG_COEF * b_h + SLEEP_BALANCE_COEF * sleep_balance
    )
    if not math.isfinite(raw):
        return ReadinessResult(
            None, None, True, len(hrv_baseline), len(rhr_baseline), components, tuple(flags)
        )
    score, clamped = round_half_up_clamped(raw)
    return ReadinessResult(
        score, clamped, False, len(hrv_baseline), len(rhr_baseline), components, tuple(flags)
    )
