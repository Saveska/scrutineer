# Scrutineer

Scrutineer checks real recordings from electric city buses against written requirements.
Every requirement states where it comes from, and every check returns PASS, FAIL or
INCONCLUSIVE, together with the exact moments in the recording that caused the result.
A language model can draft new requirements from plain sentences, but a person approves
every draft, and the model never decides whether a recording passes.

**Live app:** https://scrutineer-fj93o7xwbz7cr7wybhq2ro.streamlit.app/

## How it works

1. **Requirements** live in `rules/requirements.yaml`. Each one has an ID, a plain-language text,
   the signals it uses, its parameters, and a source: a regulation, the dataset documentation,
   or a value observed in the data. Observed values are labelled as such.
2. **Checks** in `src/scrutineer/checks.py` turn each requirement into code. Each returns:
   - **PASS** if every row could be judged and none broke the rule,
   - **FAIL** if at least one stretch of rows broke the rule, with start time, end time and worst value,
   - **INCONCLUSIVE** if missing data could be hiding a violation.
     A missing value only counts if it could change the answer.
3. **The engine** reads the requirements file and runs the matching check, with parameters
   taken from the file. Only functions named `check_...` can be called from the file.
4. **Fault injection** plants known faults into copies of real journeys and measures which
   checks catch them.
5. **AI-assisted rule drafting** turns a requirement sentence into a rule entry, using one of
   four allowed rule types. Code validates the draft, a person approves it, and the engine runs it.

## Requirements

| ID | Rule | Source |
|---|---|---|
| REQ-001 | No door may be open while the bus moves faster than 5 km/h | UN Regulation No. 107, Annex 3 para 7.6.5.1.9 |
| REQ-002 | The halt brake must be active once the bus has stood still for more than 3 s | Dataset paper, Table 1; grace period observed from data |
| REQ-003 | The electric drive must not apply traction force above 100 N while a door is open, except in the last 2 s before the door closes | Derived from UN R107, para 2.27 and Annex 3 para 7.6.5.9; parameters observed from data |
| REQ-004 | Electric power demand must stay between -340 and +370 kW | Dataset paper, "Statistical analysis"; margin added after seeing the data |
| REQ-005 | Vehicle control unit signals must have no gap of 10 s or more | Dataset paper, "Technical Validation" |

The full sources, exact paragraphs and notes are in `rules/requirements.yaml`.

## Findings on the sample data

These results come from the 10 sample journeys of the ZTBus dataset
(bus 183 and bus 208, 2019 to 2022).

### Data quality

- All 10 journeys were sampled exactly once per second, with no missing timestamps.
- No vehicle control unit signal had a gap of 10 seconds or more (REQ-005),
  which matches the dataset paper's selection criteria.
- In 3 of the 10 journeys, the door flag is empty on the final row of the file.
  The halt brake flag also contains empty values in those same 3 journeys.
- In the journey from 24 June 2019, the halt brake flag is 0 for the entire recording,
  although the brake pressure at standstill is similar to the other journeys.
  The flag appears not to have been recorded in that journey. The dataset paper
  does not mention this.

### Requirement results

| ID | Rule | Result |
|---|---|---|
| REQ-001 | No door open above 5 km/h | 10 PASS |
| REQ-002 | Halt brake active after 3 s of standstill | 1 PASS, 8 FAIL, 1 INCONCLUSIVE |
| REQ-003 | No traction force above 100 N with a door open | 10 PASS |
| REQ-004 | Power demand between -340 and +370 kW | 10 PASS |
| REQ-005 | No signal gap of 10 s or more | 10 PASS |

A FAIL means the recording breaks the rule as written. It does not by itself mean the
vehicle is faulty, the cause still needs investigation.

### Observations behind the results

- **Doors (REQ-001):** no door was ever open while the bus moved faster than 5 km/h.
- **Halt brake (REQ-002):** in the 9 journeys where the flag was recorded, 99.85% of stops
  where the brake came on did so within 3 seconds, which is where the grace period comes from.
  The check flagged 52 stops longer than 3 seconds where the brake did not come on in time.
  The cause cannot be determined from the data alone.
- **Traction force (REQ-003):** with a door open, the drive almost never pushed. The rare
  exceptions all happened within the last 2 seconds before the door closed, which looks like the bus starting
  to pull away.
- **Power (REQ-004):** several journeys went slightly above the paper's approximate peak of
  350 kW during normal acceleration. Since the paper's figures are approximate, a 20 kW margin
  was added on each side. This margin was chosen after seeing the data.

## Fault injection

Seven fault types were planted into copies of the 10 sample journeys,
5 times per journey at random but realistic places (fixed seed 42).
A fault counts as caught only if the target rule reports a violation
in the changed rows, so real events already in the data are not counted.

| Fault | Target | Trials | Caught |
|---|---|---|---|
| Door stuck open while driving (5 s) | REQ-001 | 50 | 50 |
| Brake signal lost during a stop | REQ-002 | 45 | 45 |
| Drive pushes with door open (3 s, 5000 N) | REQ-003 | 50 | 50 |
| Power spike (600 kW, 3 s) | REQ-004 | 50 | 50 |
| Speed missing for 15 s | REQ-005 | 50 | 50 |
| Speed missing for 5 s (designed miss) | REQ-005 | 50 | 0 |
| Speed frozen for 20 s (designed miss) | none | 50 | 0 |

- "Brake signal lost" has 45 trials, because the 2019 journey has no working brake stops to break.
- A frozen speed signal was not detected by any rule. A rule comparing wheel speeds
  with vehicle speed would likely catch it.
- The faults were designed to clearly break the rules, so these rates show the checks
  work as built. They do not show how many real-world faults would be caught.

## AI-assisted rule drafting

A language model (Gemini 3.5 Flash-Lite) turns a requirement sentence into a
rule entry, using one of four allowed rule types and only the columns in the dataset.
Code validates the draft, a person approves it, and only then does the engine run it.
The model never sees the data and never decides PASS or FAIL.

The model can write new rules within these four types. It cannot invent a new type of rule,
because that would mean running code written by the model. Sentences that need a new type
are refused.

### Evaluation

18 sentences with known answers (`evaluation/rule_drafting_cases.yaml`): 14 that should
become rules, covering unit conversions, and 4 that should be
refused because the data has no matching signal or rule type.

The evaluation was run twice, with 17 of 18 correct both times.

- All 4 refusals were correct in both runs. For example, the model did not invent a
  battery temperature signal.
- In the run shown in the app, the one error was for "The bus must not drive faster than 70 km/h":
  the model set a minimum speed that the sentence did not state. This matters, because the recorded
  speed is sometimes slightly negative when the bus starts or stops, so an unstated minimum can cause
  false failures.
- Outputs vary between runs, even with temperature set to 0.

## Security and responsible AI

- The model's answer is only read as JSON and checked against a fixed list of rule types
  and columns. Nothing it returns is run as code, so a manipulated prompt can at most
  produce a wrong or refused draft.
- In the app, an approved rule runs only for that session. The requirements file is not changed.
- The app limits each session to 5 drafts to protect the free quota.

## Limitations

- This is offline analysis of recorded data. It is not rig or hardware testing.
- Only 10 of the 1409 journeys in the dataset were used.
- Several parameters (the 3 s and 2 s grace periods, the 100 N limit, the power margin)
  were chosen from the same 10 journeys the rules were then run on.
- The requirements are mine, based on public sources. They are not real manufacturer
  requirements. It is not confirmed that UN R107 applies to these particular buses.
  The R107 text used is the 2015 version on EUR-Lex.

## Run it locally

Requires Python 3.11 or newer.

    pip install -r requirements.txt pytest
    pytest                              # runs the 41 unit tests
    streamlit run app/streamlit_app.py  # starts the app

AI drafting also needs a Gemini API key in a `.env` file: `GEMINI_API_KEY=your-key`.

## Credits

- **Data:** ZTBus dataset by Fabio Widmer, Andreas Ritter and Christopher H. Onder,
  ETH Zurich, https://doi.org/10.3929/ethz-b-000626723, licensed under
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Described in
  "ZTBus: A Large Dataset of Time-Resolved City Bus Driving Missions",
  Scientific Data 10, 687 (2023), https://doi.org/10.1038/s41597-023-02600-6.
  The sample journeys in this repository are compressed copies, their contents are unchanged.
  This project is not affiliated with or endorsed by the authors.
- **Regulation:** UN Regulation No. 107 (buses), as published on EUR-Lex:
  https://eur-lex.europa.eu/eli/reg/2015/107/oj/eng
- **Language model:** Google Gemini API.
