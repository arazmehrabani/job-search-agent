# Demo

The repository includes a synthetic-data dashboard demo so the UI can be inspected without publishing a real job-search database.

## Build the demo

```bash
python scripts/build_demo_dashboard.py
```

The script creates a temporary SQLite database with fictional employers and job URLs, renders the real dashboard code, and writes:

```text
output/demo_dashboard.html
docs/assets/dashboard-demo.png
```

The PNG is suitable for the README. The HTML can be opened locally for a closer look.

## What the dashboard demonstrates

- **Fit**: evidence-backed estimate of how well the candidate satisfies the role.
- **Priority**: practical recommendation for whether the role deserves application effort.
- **Evaluation stage**: local PRE or deeper evaluation state.
- **German requirement**: explicit/contextual language requirement display.
- **Career family / tier**: target, adjacent, or stretch classification.
- **Decision controls**: Interested, Save, Skip, and later outcomes.
- **Audit rows**: filtered or non-actionable jobs remain inspectable instead of disappearing silently.

The demo data is deliberately synthetic and does not represent real vacancies or employers.
