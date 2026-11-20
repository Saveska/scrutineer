"""Engine: read requirements from YAML and run the matching checks."""
import inspect

import pandas as pd
import yaml

from scrutineer import checks
from scrutineer.data import load_journey

# Only functions whose names start with "check_" can be run from the YAML file.
# This stops a requirement from calling anything else in the code,
# which matters once the AI starts writing YAML entries.
CHECKS = {name: fn for name, fn in vars(checks).items()
          if name.startswith("check_") and callable(fn)}


def load_requirements(path):
    """Read the requirements file and make sure every entry can actually run."""
    with open(path, encoding="utf-8") as f:
        requirements = yaml.safe_load(f)

    for req in requirements:
        rid = req.get("id", "<no id>")
        if "check" not in req:
            raise ValueError(f"{rid}: no 'check' field")
        if req["check"] not in CHECKS:
            raise ValueError(f"{rid}: unknown check '{req['check']}'")
        accepted = inspect.signature(CHECKS[req["check"]]).parameters
        for param in (req.get("parameters") or {}):
            if param not in accepted:
                raise ValueError(f"{rid}: '{req['check']}' has no parameter '{param}'")
    return requirements


def run_requirements(df, requirements):
    """Run every requirement on one journey, using the parameters from the file."""
    results = []
    for req in requirements:
        check = CHECKS[req["check"]]
        params = req.get("parameters") or {}
        results.append(check(df, requirement_id=req["id"], **params))
    return results


def run_on_journeys(files, requirements_path):
    """Run all requirements on all journeys. One row per journey and requirement."""
    requirements = load_requirements(requirements_path)
    rows = []
    for p in files:
        df = load_journey(p)
        for r in run_requirements(df, requirements):
            rows.append({
                "journey": p.name[:15],
                "requirement": r.requirement_id,
                "status": r.status,
                "violations": len(r.violations),
                "rows_evaluated": r.rows_evaluated,
                "note": r.note,
            })
    return pd.DataFrame(rows)