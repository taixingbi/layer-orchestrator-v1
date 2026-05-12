# Gold test (router eval)

Runs **`POST /orchestrator/eval/router`** for every row in each CSV under **`data/`**, and writes one results CSV per input under **`result/`**.

## Layout

- **`data/*.csv`** — gold inputs (`question,expected_route`; route is the field after the **last** comma).
- **`run-router-eval.sh`** — batch runner (works from any working directory).
- **`result/<name>.csv`** — outputs (same basename as each input), e.g. `data/router-gold-profile.csv` → `result/router-gold-profile.csv`.

## Run

From repo root (or anywhere):

```bash
bash gold-test/run-router-eval.sh
```

## Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `DATA_DIR` | `<gold-test>/data` | Directory of input `*.csv` |
| `RESULT_DIR` | `<gold-test>/result` | Directory for output `*.csv` |
| `ORCHESTRATOR_URL` | `http://192.168.86.179:30184` | Base URL (no path) |
| `CONCURRENCY` | `4` | Parallel HTTP workers per file |

## Input CSV

- Header: **`question,expected_route`**
- **`question`**: everything before the final `,expected_route` segment (commas inside the question are OK).

## Output CSV columns

`question`, `expected_route`, `actual_route`, `route_match`

## Suites

- **`data/router-gold-profile.csv`** — candidate / profile–style questions (+ one `direct_reply` control).
- **`data/router-gold-mixed.csv`** — profile, policy, immigration, and generic follow-ups.

Generated **`result/*.csv`** files are ignored by git (see `.gitignore`); re-run the script to regenerate them.
