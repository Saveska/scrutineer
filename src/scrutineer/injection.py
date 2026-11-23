"""Fault injection: plant known faults into copies of real journeys and measure
which checks catch them."""
import numpy as np
import pandas as pd

from scrutineer.data import load_journey
from scrutineer.engine import load_requirements, run_requirements

def run_all(df, requirements):
    """Run every requirement from the requirements file on one journey."""
    return {r.requirement_id: r for r in run_requirements(df, requirements)}

# ---------------------------------------------------------------------------
# Helpers for choosing where a fault can go
# ---------------------------------------------------------------------------

def _window_starts(mask, length):
    """Rows where mask is True for `length` rows in a row, given as the first row."""
    full = mask.astype(int).rolling(length).sum() == length
    return (full[full].index - (length - 1)).tolist()


def _stop_blocks(df):
    """Every standstill (speed <= 0) as a list of row numbers."""
    stopped = df["odometry_vehicleSpeed"] <= 0
    run_id = (stopped != stopped.shift(fill_value=False)).cumsum()
    return [b.index for _, b in df[stopped].groupby(run_id[stopped])]


def _plant(df, column, first, last, value):
    """Return a copy of df with rows first..last of column set to value."""
    out = df.copy()
    out.loc[first:last, column] = value
    return out, first, last


# ---------------------------------------------------------------------------
# Faults. Each returns (damaged copy, first row, last row), or None if this
# journey has no suitable place for it.
# ---------------------------------------------------------------------------

def door_stuck_open(df, rng, length=5):
    """Door flag stuck at 1 while the bus drives faster than 5 km/h with doors closed."""
    driving = (df["odometry_vehicleSpeed"] * 3.6 > 5) & (df["status_doorIsOpen"] == 0)
    starts = _window_starts(driving, length)
    if not starts:
        return None
    s = int(rng.choice(starts))
    return _plant(df, "status_doorIsOpen", s, s + length - 1, 1)


def brake_signal_lost(df, rng, min_stop_s=8, grace_s=3):
    """Halt brake flag drops to 0 for a whole stop where it was working."""
    halt = df["status_haltBrakeIsActive"]
    blocks = [b for b in _stop_blocks(df)
              if len(b) >= min_stop_s and (halt[b[: grace_s + 1]] == 1).any()]
    if not blocks:
        return None
    b = blocks[int(rng.integers(len(blocks)))]
    return _plant(df, "status_haltBrakeIsActive", b[0], b[-1], 0)


def drive_push_door_open(df, rng, length=3, close_grace_s=2):
    """Drive applies 5000 N with a door open, outside the closing tolerance."""
    door_open = df["status_doorIsOpen"] == 1
    starts = _window_starts(door_open, length + close_grace_s)
    if not starts:
        return None
    s = int(rng.choice(starts))
    return _plant(df, "traction_tractionForce", s, s + length - 1, 5000.0)


def power_spike(df, rng, length=3):
    """Power demand jumps to an impossible 600 kW."""
    starts = _window_starts(df["electric_powerDemand"].notna(), length)
    if not starts:
        return None
    s = int(rng.choice(starts))
    return _plant(df, "electric_powerDemand", s, s + length - 1, 600_000.0)


def speed_dropout(df, rng, length):
    """Speed signal missing for `length` seconds."""
    starts = _window_starts(df["odometry_vehicleSpeed"].notna(), length)
    if not starts:
        return None
    s = int(rng.choice(starts))
    return _plant(df, "odometry_vehicleSpeed", s, s + length - 1, np.nan)


def frozen_speed(df, rng, length=20):
    """Speed stuck at one value while the bus is really driving."""
    driving = df["odometry_vehicleSpeed"] * 3.6 > 5
    starts = _window_starts(driving, length)
    if not starts:
        return None
    s = int(rng.choice(starts))
    return _plant(df, "odometry_vehicleSpeed", s, s + length - 1,
                  df.loc[s, "odometry_vehicleSpeed"])


FAULTS = [
    {"name": "door stuck open",          "inject": door_stuck_open,      "target": "REQ-001", "expected": "caught"},
    {"name": "brake signal lost",        "inject": brake_signal_lost,    "target": "REQ-002", "expected": "caught"},
    {"name": "drive pushes, door open",  "inject": drive_push_door_open, "target": "REQ-003", "expected": "caught"},
    {"name": "power spike",              "inject": power_spike,          "target": "REQ-004", "expected": "caught"},
    {"name": "long speed dropout (15 s)",
     "inject": lambda df, rng: speed_dropout(df, rng, 15),               "target": "REQ-005", "expected": "caught"},
    {"name": "short speed dropout (5 s)",
     "inject": lambda df, rng: speed_dropout(df, rng, 5),                "target": "REQ-005", "expected": "missed"},
    {"name": "frozen speed (20 s)",      "inject": frozen_speed,         "target": None,      "expected": "missed"},
]


# ---------------------------------------------------------------------------
# Campaign
# ---------------------------------------------------------------------------

def _overlaps(result, first, last):
    """True if any violation in result touches rows first..last."""
    return any(v.first_row <= last and v.last_row >= first for v in result.violations)


def run_campaign(files, requirements_path, trials_per_journey=5, seed=42):
    """Plant every fault several times in every journey and record what was caught."""
    requirements = load_requirements(requirements_path)
    rng = np.random.default_rng(seed)
    rows = []
    for p in files:
        clean = load_journey(p)
        baseline = run_all(clean, requirements)
        for fault in FAULTS:
            for _ in range(trials_per_journey):
                planted = fault["inject"](clean, rng)
                if planted is None:
                    break  # no suitable place in this journey
                damaged, first, last = planted
                results = run_all(damaged, requirements)
                target = fault["target"]
                if target:
                    caught = _overlaps(results[target], first, last)
                else:
                    caught = any(_overlaps(r, first, last) for r in results.values())
                changed = [rid for rid in results
                           if rid != target and results[rid].status != baseline[rid].status]
                rows.append({
                    "journey": p.name[:15],
                    "fault": fault["name"],
                    "target": target or "none",
                    "expected": fault["expected"],
                    "first_row": first,
                    "last_row": last,
                    "caught": caught,
                    "other_rules_changed": ", ".join(changed),
                })
    return pd.DataFrame(rows)


def summarize(trials):
    """One row per fault: trials, caught, missed, catch rate."""
    out = (trials.groupby(["fault", "target", "expected"], sort=False)
                 .agg(trials=("caught", "size"), caught=("caught", "sum"))
                 .reset_index())
    out["missed"] = out["trials"] - out["caught"]
    out["catch_rate_%"] = (out["caught"] / out["trials"] * 100).round(1)
    return out