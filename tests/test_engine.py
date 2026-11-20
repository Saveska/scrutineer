import pandas as pd
import pytest

from scrutineer.checks import FAIL, PASS
from scrutineer.engine import load_requirements, run_requirements


def test_real_requirements_file_loads():
    reqs = load_requirements("rules/requirements.yaml")
    assert [r["id"] for r in reqs] == ["REQ-001", "REQ-002", "REQ-003", "REQ-004", "REQ-005"]


def test_parameters_from_file_are_used(tmp_path):
    path = tmp_path / "reqs.yaml"
    path.write_text(
        "- id: T-1\n"
        "  check: check_door_speed\n"
        "  parameters:\n"
        "    limit_kmh: 1.0\n"
    )
    df = pd.DataFrame({
        "time_iso": pd.date_range("2024-01-01", periods=1, freq="s", tz="UTC"),
        "status_doorIsOpen": [1],
        "odometry_vehicleSpeed": [0.5],   # 1.8 km/h: fine at 5 km/h, a violation at 1 km/h
    })
    assert run_requirements(df, load_requirements(path))[0].status == FAIL


def test_unknown_check_is_rejected(tmp_path):
    path = tmp_path / "reqs.yaml"
    path.write_text("- id: T-1\n  check: delete_everything\n")
    with pytest.raises(ValueError, match="unknown check"):
        load_requirements(path)


def test_unknown_parameter_is_rejected(tmp_path):
    path = tmp_path / "reqs.yaml"
    path.write_text("- id: T-1\n  check: check_door_speed\n  parameters:\n    limit_khm: 5\n")
    with pytest.raises(ValueError, match="no parameter"):
        load_requirements(path)