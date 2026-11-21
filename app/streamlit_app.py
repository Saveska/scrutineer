"""Scrutineer web app. Run from the project root with:
    streamlit run app/streamlit_app.py
"""
import os
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from scrutineer.data import find_journey_files, load_journey
from scrutineer.engine import load_requirements, run_requirements

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "rules" / "requirements.yaml"
RESULTS = ROOT / "app" / "results"
DATA_DIR = ROOT / "data" if (ROOT / "data").exists() else ROOT / "app" / "sample_data"
MAX_DRAFTS = 5   # AI drafts per visitor session, to protect the free API quota

STATUS_COLORS = {"PASS": "#409554", "FAIL": "#a93942", "INCONCLUSIVE": "#958140"}

st.set_page_config(page_title="Scrutineer", layout="wide")


# ---------------------------------------------------------------------------
# Cached data
# ---------------------------------------------------------------------------

@st.cache_data
def journey_files():
    return {p.name[:15]: str(p) for p in find_journey_files(DATA_DIR)}


@st.cache_data
def journey(path):
    return load_journey(path)


@st.cache_data
def requirements():
    return load_requirements(REQUIREMENTS)


@st.cache_data
def journey_results(path):
    return run_requirements(journey(path), requirements())


@st.cache_data
def audit():
    rows = []
    for name, path in journey_files().items():
        for r in journey_results(path):
            rows.append({"journey": name, "requirement": r.requirement_id, "status": r.status})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def color_status(value):
    return f"background-color: {STATUS_COLORS.get(value, '')}"


def signals_of(req):
    """Columns worth showing for a requirement, with speed always first."""
    cols = list(req.get("signals") or [])
    params = req.get("parameters") or {}
    for key in ("flag", "signal"):
        if key in params:
            cols.append(params[key])
    if "odometry_vehicleSpeed" not in cols:
        cols.insert(0, "odometry_vehicleSpeed")
    return list(dict.fromkeys(cols))


def plot_violation(df, v, req, margin_s=60):
    cols = signals_of(req)[:4]
    first = max(v.first_row - margin_s, 0)
    last = min(v.last_row + margin_s, len(df) - 1)
    w = df.loc[first:last]
    fig = make_subplots(rows=len(cols), cols=1, shared_xaxes=True,
                        subplot_titles=[f"{c} (m/s)" if "Speed" in c else c for c in cols])
    for i, c in enumerate(cols, start=1):
        shape = "hv" if c.startswith("status_") else "linear"
        fig.add_trace(go.Scatter(x=w["time_iso"], y=w[c], mode="lines", line_shape=shape),
                      row=i, col=1)
    fig.add_vrect(x0=v.start_time, x1=v.end_time + pd.Timedelta(seconds=1),
                  fillcolor="red", opacity=0.15, line_width=0, row="all", col=1)
    fig.update_layout(height=200 * len(cols), showlegend=False, margin=dict(t=40, b=20))
    st.plotly_chart(fig, use_container_width=True)
    
def show_violations(df, result, req, key):
    """Pick one violation of a result and show its chart and evidence rows."""
    if not result.violations:
        st.success("No violations.")
        return
    vi = st.selectbox(
        "Violation", range(len(result.violations)), key=key,
        format_func=lambda i: f"{result.violations[i].start_time:%H:%M:%S} to "
                              f"{result.violations[i].end_time:%H:%M:%S}, "
                              f"{result.violations[i].n_rows} s, {result.worst_value_label}: "
                              f"{result.violations[i].worst_value:,.1f}",
    )
    v = result.violations[vi]
    plot_violation(df, v, req)
    st.subheader("Evidence rows")
    first = max(v.first_row - 5, 0)
    st.dataframe(df.loc[first:v.last_row + 5, ["time_iso"] + signals_of(req)])


def api_key_available():
    try:
        if "GEMINI_API_KEY" in st.secrets:
            os.environ["GEMINI_API_KEY"] = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass   # no secrets file when running locally
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    return bool(os.environ.get("GEMINI_API_KEY"))


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def page_overview():
    st.title("Scrutineer")
    st.write(
        "Scrutineer checks real recordings from electric trolley buses in Zurich against "
        "written requirements. Every requirement states where it comes from, and every "
        "result is PASS, FAIL or INCONCLUSIVE, with the exact moments that caused it."
    )
    st.subheader("Results on the sample journeys")
    table = audit().pivot(index="journey", columns="requirement", values="status")
    st.dataframe(table.style.map(color_status))
    st.caption(
        "FAIL means the recording breaks the rule as written; the cause still needs "
        "investigation. INCONCLUSIVE means the data was not enough to judge."
    )


def page_requirements():
    st.title("Requirements")
    for req in requirements():
        with st.expander(f"{req['id']}: {str(req.get('text', '')).strip()}"):
            source_type = req.get("source_type", [])
            if isinstance(source_type, str):
                source_type = [source_type]
            st.markdown(f"**Check:** `{req['check']}`")
            st.markdown(f"**Parameters:** {req.get('parameters')}")
            st.markdown(f"**Source type:** {', '.join(source_type)}")
            st.markdown(f"**Source:** {req.get('source', '')}")
            if req.get("notes"):
                st.markdown(f"**Notes:** {req['notes']}")


def page_journey():
    st.title("Journey explorer")
    files = journey_files()
    name = st.selectbox("Journey", list(files))
    df = journey(files[name])
    results = journey_results(files[name])

    summary = pd.DataFrame([{
        "requirement": r.requirement_id,
        "status": r.status,
        "rows evaluated": r.rows_evaluated,
        "violations": len(r.violations),
        "note": r.note,
    } for r in results])
    st.dataframe(summary.style.map(color_status, subset=["status"]), hide_index=True)

    failing = [r for r in results if r.violations]
    if not failing:
        st.success("No violations in this journey.")
        return

    ri = st.selectbox("Requirement with violations", range(len(failing)),
                      format_func=lambda i: f"{failing[i].requirement_id} "
                                            f"({len(failing[i].violations)} violations)")
    r = failing[ri]
    req = next(q for q in requirements() if q["id"] == r.requirement_id)
    show_violations(df, r, req, key="journey_violation")


def page_injection():
    st.title("Fault injection")
    st.write(
        "Known faults were planted into copies of the sample journeys, 5 times per journey "
        "at random but realistic places (fixed seed). A fault counts as caught only if the "
        "target rule reports a violation in the changed rows."
    )
    path = RESULTS / "fault_injection_summary.csv"
    if path.exists():
        st.dataframe(pd.read_csv(path), hide_index=True)
    else:
        st.info("No saved results yet. Save the campaign summary to app/results/fault_injection_summary.csv.")
    st.caption(
        "The faults were designed to clearly break the rules, so these rates show the checks "
        "work as built. They do not show how many real-world faults would be caught."
    )

EXAMPLES = [
    "Power demand must stay below 350 kW.",
    "While a door is open, the vehicle speed must not exceed 1 km/h.",
    "The battery temperature must stay below 45 °C.",
]


def use_example(text):
    st.session_state["sentence"] = text


def page_ai():
    st.title("AI rule drafting")
    st.write(
        "Type a requirement. The model drafts a rule using one of four allowed rule types "
        "and only the columns in the dataset. Code validates the draft, and you decide "
        "whether to run it. The model never sees the data and never decides PASS or FAIL."
    )

    path = RESULTS / "ai_evaluation.csv"
    if path.exists():
        e = pd.read_csv(path)
        st.metric("Evaluation on sentences with known answers", f"{e['passed'].sum()} of {len(e)} correct")
        with st.expander("Evaluation details"):
            st.dataframe(e[["sentence", "outcome"]], hide_index=True)

    if not api_key_available():
        st.warning("No API key configured, so drafting is turned off.")
        return

    from scrutineer.ai import draft_rule, to_yaml_entry

    st.write("Try an example:")
    for example in EXAMPLES:
        st.button(example, on_click=use_example, args=(example,))

    sentence = st.text_input(
        "Requirement", key="sentence",
        placeholder="While the park brake is active, the vehicle speed must not exceed 1 km/h.",
    )
    used = st.session_state.get("drafts_used", 0)
    if st.button("Draft rule", disabled=used >= MAX_DRAFTS) and sentence.strip():
        st.session_state["drafts_used"] = used + 1
        with st.spinner("Asking the model..."):
            try:
                st.session_state["draft"] = draft_rule(sentence.strip())
            except Exception:
                st.error("The AI service is busy or unavailable right now. Please try again in a minute.")
                return
        st.session_state.pop("approved", None)   # a new draft needs a new approval
    if used >= MAX_DRAFTS:
        st.caption("Draft limit for this session reached.")

    d = st.session_state.get("draft")
    if d is None:
        return
    st.subheader("Draft for review")
    st.text(d.summary())
    if not d.can_express or d.problems:
        st.warning("This draft cannot be run.")
        return

    if st.button("Approve and run on all journeys"):
        st.session_state["approved"] = to_yaml_entry(d, "AI-1")
    entry = st.session_state.get("approved")
    if entry is None:
        return

    files = journey_files()
    results = {name: run_requirements(journey(p), [entry])[0] for name, p in files.items()}
    label = next(iter(results.values())).worst_value_label

    st.subheader("Results on all sample journeys")
    table = pd.DataFrame([{
        "journey": name,
        "status": r.status,
        "violations": len(r.violations),
        "worst value": max((v.worst_value for v in r.violations), default=None),
        "note": r.note,
    } for name, r in results.items()])
    st.dataframe(table.style.map(color_status, subset=["status"]), hide_index=True)
    st.caption(f"Worst value: {label}. Approved for this session only; the requirements file is not changed.")

    failing = [name for name, r in results.items() if r.violations]
    if failing:
        name = st.selectbox("Look at a journey with violations", failing, key="ai_journey")
        show_violations(journey(files[name]), results[name], entry, key="ai_violation")


PAGES = {
    "Overview": page_overview,
    "Requirements": page_requirements,
    "Journey explorer": page_journey,
    "Fault injection": page_injection,
    "AI rule drafting": page_ai,
}

page = st.sidebar.radio("Page", list(PAGES))
st.sidebar.markdown("---")
st.sidebar.caption(
    "Data: ZTBus dataset, Widmer, Ritter and Onder, ETH Zurich, "
    "[doi.org/10.3929/ethz-b-000626723](https://doi.org/10.3929/ethz-b-000626723), "
    "CC BY 4.0. Processed by Scrutineer. Not affiliated with or endorsed by the authors."
)
PAGES[page]()