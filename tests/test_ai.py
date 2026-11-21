from scrutineer.ai import Draft, grade, validate


def make(type_, params, can=True):
    return Draft("test sentence", can, "", type_, params, [])


def test_valid_draft_has_no_problems():
    d = make("check_limit_while_flag",
             {"flag": "status_doorIsOpen", "signal": "odometry_vehicleSpeed", "max_value": 1.39})
    assert validate(d) == []


def test_unknown_column_is_rejected():
    d = make("check_signal_range",
             {"signal": "battery_temperature", "min_value": None, "max_value": 318.15})
    assert any("unknown numeric column" in p for p in validate(d))


def test_unknown_rule_type_is_rejected():
    assert validate(make("delete_everything", {}))


def test_range_needs_at_least_one_bound():
    d = make("check_signal_range",
             {"signal": "odometry_vehicleSpeed", "min_value": None, "max_value": None})
    assert any("at least one bound" in p for p in validate(d))


def test_grade_allows_small_rounding():
    d = make("check_limit_while_flag",
             {"flag": "status_doorIsOpen", "signal": "odometry_vehicleSpeed", "max_value": 1.39})
    expected = {"type": "check_limit_while_flag",
                "parameters": {"flag": "status_doorIsOpen", "signal": "odometry_vehicleSpeed",
                               "max_value": 1.3889}}
    assert grade(d, expected) == "correct"


def test_grade_refusal():
    assert grade(make(None, None, can=False), "cannot_express") == "correctly refused"