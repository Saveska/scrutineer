import pandas as pd

from scrutineer.checks import (FAIL, INCONCLUSIVE, PASS, check_door_speed, check_halt_brake, check_door_traction, check_power_range)


def make_df(door, speed_ms):
    return pd.DataFrame({
        "time_iso": pd.date_range("2024-01-01", periods=len(door), freq="s", tz="UTC"),
        "status_doorIsOpen": door,
        "odometry_vehicleSpeed": speed_ms,
    })


# REQ-001 door and speed
def test_pass_when_door_open_only_while_stopped():
    assert check_door_speed(make_df([0, 1, 1, 0], [5.0, 0.0, 0.0, 5.0])).status == PASS

def test_fast_driving_with_door_closed_is_fine():
    assert check_door_speed(make_df([0, 0], [10.0, 10.0])).status == PASS

def test_boundary_just_below_and_just_above_limit():
    assert check_door_speed(make_df([1], [1.38])).status == PASS   # 4.97 km/h
    assert check_door_speed(make_df([1], [1.40])).status == FAIL   # 5.04 km/h

def test_consecutive_bad_rows_become_one_violation():
    r = check_door_speed(make_df([1, 1, 1, 1, 1], [3.0, 3.0, 3.0, 0.0, 3.0]))
    assert r.status == FAIL
    assert len(r.violations) == 2
    assert r.violations[0].n_rows == 3

def test_missing_speed_while_door_open_is_inconclusive():
    assert check_door_speed(make_df([1, 1], [0.0, float("nan")])).status == INCONCLUSIVE

def test_unknown_door_while_stopped_cannot_hide_a_violation():
    assert check_door_speed(make_df([0, float("nan")], [5.0, 0.0])).status == PASS

def test_unknown_door_while_fast_is_inconclusive():
    assert check_door_speed(make_df([0, float("nan")], [5.0, 5.0])).status == INCONCLUSIVE

def test_missing_column_is_inconclusive():
    df = make_df([1], [0.0]).drop(columns=["odometry_vehicleSpeed"])
    assert check_door_speed(df).status == INCONCLUSIVE


# REQ-002 halt brake
def make_brake_df(speed, halt):
    return pd.DataFrame({
        "time_iso": pd.date_range("2024-01-01", periods=len(speed), freq="s", tz="UTC"),
        "odometry_vehicleSpeed": speed,
        "status_haltBrakeIsActive": halt,
    })


def test_brake_on_within_grace_passes():
    df = make_brake_df([5, 0, 0, 0, 0, 0, 5], [0, 0, 1, 1, 1, 1, 0])
    assert check_halt_brake(df).status == PASS


def test_long_stop_without_brake_fails():
    df = make_brake_df([5, 0, 0, 0, 0, 0, 5], [1, 0, 0, 0, 0, 0, 0])
    r = check_halt_brake(df)
    assert r.status == FAIL
    assert len(r.violations) == 1
    assert r.violations[0].worst_value == 5   # stood still for 5 s


def test_brake_too_late_fails():
    # brake comes on at second 4 of the stop, one second after the grace period
    df = make_brake_df([5, 0, 0, 0, 0, 0, 0, 5], [1, 0, 0, 0, 0, 1, 1, 0])
    assert check_halt_brake(df).status == FAIL


def test_short_stop_is_ignored():
    df = make_brake_df([5, 0, 0, 5, 5], [1, 0, 0, 0, 0])
    assert check_halt_brake(df).status == PASS


def test_blank_flag_during_grace_is_inconclusive():
    df = make_brake_df([5, 0, 0, 0, 0, 0, 5], [1, float("nan"), 0, 0, 0, 0, 0])
    assert check_halt_brake(df).status == INCONCLUSIVE


def test_dead_signal_is_inconclusive():
    df = make_brake_df([5, 0, 0, 0, 0, 0, 5], [0] * 7)
    assert check_halt_brake(df).status == INCONCLUSIVE
    
    
# REQ-003 door and traction force
def make_force_df(door, force):
    return pd.DataFrame({
        "time_iso": pd.date_range("2024-01-01", periods=len(door), freq="s", tz="UTC"),
        "status_doorIsOpen": door,
        "traction_tractionForce": force,
    })


def test_no_force_while_door_open_passes():
    assert check_door_traction(make_force_df([0, 1, 1, 0], [5000, 0, 0, 5000])).status == PASS


def test_push_while_door_open_fails():
    assert check_door_traction(make_force_df([1, 1, 1, 1, 1, 0], [0, 5000, 0, 0, 0, 0])).status == FAIL


def test_push_in_last_two_seconds_before_closing_is_ignored():
    assert check_door_traction(make_force_df([1, 1, 1, 1, 0], [0, 0, 5000, 5000, 5000])).status == PASS


def test_push_three_seconds_before_closing_fails():
    assert check_door_traction(make_force_df([1, 1, 1, 1, 0], [0, 5000, 0, 0, 0])).status == FAIL


def test_missing_force_while_door_open_is_inconclusive():
    assert check_door_traction(make_force_df([1, 1, 1, 1, 0], [0, float("nan"), 0, 0, 0])).status == INCONCLUSIVE


def test_door_open_at_end_of_recording_gets_no_tolerance():
    assert check_door_traction(make_force_df([1, 1, 1], [0, 0, 5000])).status == FAIL
    
    
# REQ-004 power range
def make_power_df(watts):
    return pd.DataFrame({
        "time_iso": pd.date_range("2024-01-01", periods=len(watts), freq="s", tz="UTC"),
        "electric_powerDemand": watts,
    })


def test_power_inside_range_passes():
    assert check_power_range(make_power_df([0, 20_000, -300_000, 340_000])).status == PASS


def test_power_boundary_upper():
    assert check_power_range(make_power_df([369_900])).status == PASS
    assert check_power_range(make_power_df([370_100])).status == FAIL


def test_power_boundary_lower():
    assert check_power_range(make_power_df([-339_900])).status == PASS
    assert check_power_range(make_power_df([-340_100])).status == FAIL


def test_missing_power_is_inconclusive():
    assert check_power_range(make_power_df([0, float("nan")])).status == INCONCLUSIVE


def test_out_of_range_stretch_becomes_one_violation():
    r = check_power_range(make_power_df([0, 400_000, 410_000, 0]))
    assert r.status == FAIL
    assert len(r.violations) == 1
    assert r.violations[0].worst_value == 410