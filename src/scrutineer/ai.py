"""AI-assisted rule drafting. A language model turns a requirement sentence into a
rule entry. The draft is validated by code and must be approved by a person before
the engine runs it. The model never sees the data and never decides PASS or FAIL."""
import json
import os
import time
from dataclasses import dataclass, field

import pandas as pd
import yaml

MODEL = "gemini-3.5-flash-lite"   # use the exact model ID that works for your key

# Units from Table 1 of the dataset paper. Text and GPS columns are left out on purpose.
NUMERIC_COLUMNS = {
    "electric_powerDemand": "W",
    "itcs_numberOfPassengers": "passengers",
    "odometry_articulationAngle": "rad",
    "odometry_steeringAngle": "rad",
    "odometry_vehicleSpeed": "m/s",
    "odometry_wheelSpeed_fl": "m/s",
    "odometry_wheelSpeed_fr": "m/s",
    "odometry_wheelSpeed_ml": "m/s",
    "odometry_wheelSpeed_mr": "m/s",
    "odometry_wheelSpeed_rl": "m/s",
    "odometry_wheelSpeed_rr": "m/s",
    "temperature_ambient": "K",
    "traction_brakePressure": "Pa",
    "traction_tractionForce": "N",
}

FLAG_COLUMNS = {
    "status_doorIsOpen": "1 when at least one door is open",
    "status_gridIsAvailable": "1 when the bus is connected to the overhead grid",
    "status_haltBrakeIsActive": "1 when the halt brake is active",
    "status_parkBrakeIsActive": "1 when the park brake is active",
}

# The only rule types the AI may use.
RULE_TYPES = {
    "check_limit_while_flag": {
        "description": "While a flag column is 1, a numeric column must not exceed max_value.",
        "parameters": {"flag": "a flag column", "signal": "a numeric column",
                       "max_value": "number, in the signal column's unit"},
    },
    "check_signal_range": {
        "description": "A numeric column must stay between min_value and max_value. "
                       "Use null for a bound the sentence does not give.",
        "parameters": {"signal": "a numeric column",
                       "min_value": "number or null, in the column's unit",
                       "max_value": "number or null, in the column's unit"},
    },
    "check_halt_brake": {
        "description": "Once the bus has stood still (speed <= 0) for more than grace_s "
                       "seconds, the halt brake must be active.",
        "parameters": {"grace_s": "number of seconds"},
    },
    "check_signal_gaps": {
        "description": "No vehicle signal may be missing for max_gap_s seconds or more.",
        "parameters": {"max_gap_s": "number of seconds"},
    },
}

NULLABLE = {"min_value", "max_value"}   # only these may be null, and only in a range


@dataclass
class Draft:
    sentence: str
    can_express: bool
    reason: str
    type: str | None
    parameters: dict | None
    assumptions: list
    problems: list = field(default_factory=list)

    def summary(self):
        lines = [f"Sentence: {self.sentence}"]
        if not self.can_express:
            lines.append(f"Cannot be expressed: {self.reason}")
        else:
            lines.append(f"Rule type: {self.type}")
            lines.append(f"Parameters: {self.parameters}")
            lines.append(f"Reasoning: {self.reason}")
            for a in self.assumptions:
                lines.append(f"Assumption: {a}")
        if self.problems:
            lines.append("Validation problems: " + "; ".join(self.problems))
        return "\n".join(lines)


def _prompt(sentence):
    columns = "\n".join(f"- {c} ({u})" for c, u in NUMERIC_COLUMNS.items())
    flags = "\n".join(f"- {c}: {d}" for c, d in FLAG_COLUMNS.items())
    return f"""You turn one requirement sentence about an electric city bus into a rule
for an automated verification tool.

Rule types you may use, with their parameters:
{json.dumps(RULE_TYPES, indent=2)}

Numeric columns, with the unit the data is stored in:
{columns}

Flag columns (0 or 1):
{flags}

Instructions:
- Use exactly one rule type and only the columns listed above.
- Convert every number into the column's unit: km/h to m/s divide by 3.6,
  kW to W multiply by 1000, kN to N multiply by 1000, degrees Celsius to K add 273.15,
  bar to Pa multiply by 100000.
- If the sentence needs a signal or a kind of rule that is not listed, set can_express
  to false and explain why. Do not guess.
- List every assumption you made.

Respond with JSON only, in this form:
{{"can_express": true or false, "reason": "short explanation",
 "type": "rule type name or null", "parameters": {{...}} or null, "assumptions": ["..."]}}

Sentence: {sentence}"""


def _ask(prompt, model, tries=4):
    from dotenv import load_dotenv
    from google import genai

    load_dotenv()
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    for attempt in range(tries):
        try:
            response = client.models.generate_content(
                model=model, contents=prompt,
                config={"response_mime_type": "application/json", "temperature": 0},
            )
            return response.text
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(5 * 2 ** attempt)   # 5, 10, 20 s, for temporary errors like 503


def validate(draft):
    """Check a draft against the allowed rule types and columns. Returns a list of problems."""
    if not draft.can_express:
        return []
    spec = RULE_TYPES.get(draft.type)
    if spec is None:
        return [f"unknown rule type '{draft.type}'"]

    problems = []
    params = draft.parameters or {}
    if set(params) != set(spec["parameters"]):
        problems.append(f"parameters should be {sorted(spec['parameters'])}, got {sorted(params)}")
    for key, value in params.items():
        if key == "flag":
            if value not in FLAG_COLUMNS:
                problems.append(f"unknown flag column '{value}'")
        elif key == "signal":
            if value not in NUMERIC_COLUMNS:
                problems.append(f"unknown numeric column '{value}'")
        elif value is None:
            if not (draft.type == "check_signal_range" and key in NULLABLE):
                problems.append(f"{key} must not be null")
        elif not isinstance(value, (int, float)) or isinstance(value, bool):
            problems.append(f"{key} must be a number")
    if draft.type == "check_signal_range" and params.get("min_value") is None \
            and params.get("max_value") is None:
        problems.append("a range needs at least one bound")
    return problems


def draft_rule(sentence, model=MODEL):
    """Ask the model for a draft and validate it. Nothing is saved here."""
    text = _ask(_prompt(sentence), model)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return Draft(sentence, False, "the model did not return valid JSON", None, None, [],
                     problems=["invalid JSON"])
    draft = Draft(
        sentence=sentence,
        can_express=bool(data.get("can_express")),
        reason=data.get("reason", ""),
        type=data.get("type"),
        parameters=data.get("parameters"),
        assumptions=data.get("assumptions") or [],
    )
    draft.problems = validate(draft)
    return draft


def to_yaml_entry(draft, requirement_id, model=MODEL):
    """Turn an approved, valid draft into a requirements file entry."""
    if not draft.can_express or draft.problems:
        raise ValueError("only valid drafts can become requirements")
    return {
        "id": requirement_id,
        "text": draft.sentence,
        "check": draft.type,
        "parameters": draft.parameters,
        "source_type": ["ai_drafted"],
        "source": f"Drafted by {model} from the requirement text, reviewed and approved by a person.",
        "notes": "; ".join(draft.assumptions) or "No assumptions listed.",
    }


def save_entry(entry, path):
    """Add an approved entry to the end of the requirements file. The rest of the
    file, including comments, is left untouched."""
    with open(path, encoding="utf-8") as f:
        existing = yaml.safe_load(f) or []
    if any(r.get("id") == entry["id"] for r in existing):
        raise ValueError(f"{entry['id']} already exists")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n" + yaml.safe_dump([entry], sort_keys=False, allow_unicode=True))


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _numbers_match(got, expected, rel=0.01):
    """Allow 1% difference, for rounding such as 1.39 vs 1.3889."""
    return abs(got - expected) <= rel * max(abs(expected), 1e-6)


def grade(draft, expected):
    """Compare a draft with the expected answer from the evaluation set."""
    if expected == "cannot_express":
        return "correctly refused" if not draft.can_express else "should have refused"
    if not draft.can_express:
        return "wrongly refused"
    if draft.problems:
        return "invalid draft"
    if draft.type != expected["type"]:
        return "wrong rule type"
    got = draft.parameters or {}
    for key, value in expected["parameters"].items():
        g = got.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if not isinstance(g, (int, float)) or not _numbers_match(g, value):
                return f"wrong value for {key}"
        elif g != value:
            return f"wrong value for {key}"
    return "correct"


def evaluate_drafting(cases_path, model=MODEL, pause_s=5):
    """Run the model on every case and grade it. pause_s keeps us under the free rate limit."""
    with open(cases_path, encoding="utf-8") as f:
        cases = yaml.safe_load(f)
    rows = []
    for case in cases:
        draft = draft_rule(case["sentence"], model)
        outcome = grade(draft, case["expected"])
        rows.append({
            "sentence": case["sentence"],
            "outcome": outcome,
            "passed": outcome in ("correct", "correctly refused"),
            "type": draft.type,
            "parameters": draft.parameters,
            "reason": draft.reason,
        })
        time.sleep(pause_s)
    return pd.DataFrame(rows)