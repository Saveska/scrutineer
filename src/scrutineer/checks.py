from dataclasses import dataclass, field

import pandas as pd

PASS, FAIL, INCONCLUSIVE = "PASS", "FAIL", "INCONCLUSIVE"


@dataclass
class Violation:
    """One continuous stretch of rows that break a rule."""
    start_time: pd.Timestamp
    end_time: pd.Timestamp
    n_rows: int
    worst_value: float  # most extreme value of the rule's signal in the stretch, see CheckResult.worst_value_label
    first_row: int
    last_row: int


@dataclass
class CheckResult:
    requirement_id: str
    status: str  # PASS, FAIL or INCONCLUSIVE
    rows_total: int
    rows_evaluated: int  # rows where we could tell whether the rule was kept or broken
    violations: list = field(default_factory=list)
    note: str = ""
    worst_value_label: str = ""  # what Violation.worst_value means, e.g. "highest speed (km/h)"


# ---------------------------------------------------------------------------
# Shared helpers. Every rule follows the same three steps:
#   1. stop early if a needed column is missing
#   2. mark which rows break the rule, and which rows could be hiding a break
#   3. turn those two masks into a CheckResult
# ---------------------------------------------------------------------------

def _missing_columns(df, needed, requirement_id):
    """Return an INCONCLUSIVE result if any needed column is absent, otherwise None."""
    absent = [c for c in needed if c not in df.columns]
    if absent:
        return CheckResult(requirement_id, INCONCLUSIVE, len(df), 0,
                           note=f"missing columns: {absent}")
    return None


def _find_violations(df, bad, signal):
    """Group consecutive bad rows into Violations; signal gives each stretch its worst_value."""
    # Give every run of consecutive bad rows its own number, then summarise each run.
    run_id = (bad != bad.shift(fill_value=False)).cumsum()
    violations = []
    for _, block in df[bad].groupby(run_id[bad]):
        violations.append(Violation(
            start_time=block["time_iso"].iloc[0],
            end_time=block["time_iso"].iloc[-1],
            n_rows=len(block),
            worst_value=float(signal[block.index].max()),
            first_row=int(block.index[0]),
            last_row=int(block.index[-1]),
        ))
    return violations


def _build_result(df, requirement_id, violations, could_hide_violation, worst_value_label):
    """Decide PASS, FAIL or INCONCLUSIVE.

    A proven violation always means FAIL. Without one, we can only say PASS
    if no row with missing data could have been hiding a violation.
    """
    rows_evaluated = int((~could_hide_violation).sum())
    if violations:
        status, note = FAIL, ""
    elif rows_evaluated == 0 or could_hide_violation.any():
        status, note = INCONCLUSIVE, f"{int(could_hide_violation.sum())} rows could not be evaluated"
    else:
        status, note = PASS, ""
    return CheckResult(requirement_id, status, len(df), rows_evaluated,
                       violations, note, worst_value_label)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def check_door_speed(df, limit_kmh=5.0, requirement_id="REQ-001"):
    """No door may be open while the bus moves faster than limit_kmh (UN R107)."""
    needed = ["time_iso", "status_doorIsOpen", "odometry_vehicleSpeed"]
    missing = _missing_columns(df, needed, requirement_id)
    if missing:
        return missing

    door_open = df["status_doorIsOpen"] == 1
    door_unknown = df["status_doorIsOpen"].isna()
    speed_kmh = df["odometry_vehicleSpeed"] * 3.6

    # A comparison with NaN is False, so unknown rows are never counted as violations.
    bad = door_open & (speed_kmh > limit_kmh)

    # Missing data only matters if it could hide a break:
    # door unknown while the bus may be moving fast, or door open with unknown speed.
    could_hide_violation = (
        (door_unknown & ~(speed_kmh <= limit_kmh))
        | (door_open & speed_kmh.isna())
    )

    violations = _find_violations(df, bad, speed_kmh)
    return _build_result(df, requirement_id, violations, could_hide_violation,
                         "highest speed (km/h)")
    
    
def check_halt_brake(df, grace_s=3, requirement_id="REQ-002"):
    """Once the bus has stood still for more than grace_s seconds, the halt brake must
    be active (dataset paper, Table 1). grace_s = 3 is observed from the data."""
    needed = ["time_iso", "odometry_vehicleSpeed", "status_haltBrakeIsActive"]
    missing = _missing_columns(df, needed, requirement_id)
    if missing:
        return missing

    halt = df["status_haltBrakeIsActive"]
    label = "standstill length (s)"

    # A flag that never switches on cannot confirm or refute the rule.
    if not (halt == 1).any():
        return CheckResult(requirement_id, INCONCLUSIVE, len(df), 0,
                           note="halt brake flag is never active in this recording",
                           worst_value_label=label)

    stopped = df["odometry_vehicleSpeed"] <= 0
    run_id = (stopped != stopped.shift(fill_value=False)).cumsum()
    # For every row, the length of the standstill it belongs to (0 while moving).
    stop_length = stopped.groupby(run_id).transform("sum")

    bad = pd.Series(False, index=df.index)
    could_hide_violation = pd.Series(False, index=df.index)
    for _, block in df[stopped].groupby(run_id[stopped]):
        if len(block) <= grace_s:
            continue  # too short to demand the brake
        window = halt[block.index[: grace_s + 1]]
        if (window == 1).any():
            continue  # brake came on in time
        if window.isna().any():
            could_hide_violation[block.index] = True  # a blank could be hiding the brake
        else:
            bad[block.index] = True

    violations = _find_violations(df, bad, stop_length)
    return _build_result(df, requirement_id, violations, could_hide_violation, label)


def check_door_traction(df, limit_n=100.0, close_grace_s=2, requirement_id="REQ-003"):
    """The drive must not push the bus (traction force above limit_n) while a door is open,
    except in the last close_grace_s seconds before the door closes. Illustrative interlock
    rule inspired by UN R107; limit_n and close_grace_s are observed from the data."""
    needed = ["time_iso", "status_doorIsOpen", "traction_tractionForce"]
    missing = _missing_columns(df, needed, requirement_id)
    if missing:
        return missing

    door_open = df["status_doorIsOpen"] == 1
    door_unknown = df["status_doorIsOpen"].isna()
    force = df["traction_tractionForce"]

    # Door-open rows in the last close_grace_s seconds before the door closes.
    # fill_value=True: if the recording ends with the door open, it never closes,
    # so those last rows get no tolerance.
    closes_soon = pd.Series(False, index=df.index)
    for k in range(1, close_grace_s + 1):
        closes_soon |= ~door_open.shift(-k, fill_value=True)
    closing = door_open & closes_soon

    bad = door_open & ~closing & (force > limit_n)
    could_hide_violation = (
        (door_unknown & ~(force <= limit_n))
        | (door_open & ~closing & force.isna())
    )

    violations = _find_violations(df, bad, force)
    return _build_result(df, requirement_id, violations, could_hide_violation,
                         "highest traction force (N)")
    
    
def check_power_range(df, min_kw=-340.0, max_kw=370.0, requirement_id="REQ-004"):
    """Electric power demand must stay within the motors' documented capacity
    (dataset paper, Statistical analysis)."""
    needed = ["time_iso", "electric_powerDemand"]
    missing = _missing_columns(df, needed, requirement_id)
    if missing:
        return missing

    kw = df["electric_powerDemand"] / 1000   # the column is in watts

    bad = (kw < min_kw) | (kw > max_kw)
    could_hide_violation = kw.isna()   # an unknown value could be out of range

    # worst_value is the largest power in either direction, so both kinds of violation are visible
    violations = _find_violations(df, bad, kw.abs())
    return _build_result(df, requirement_id, violations, could_hide_violation,
                         "largest power magnitude (kW)")