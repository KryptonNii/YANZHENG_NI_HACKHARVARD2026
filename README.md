# TrialPilot

> Placeholder README — the full version is written by A11 (docs).

**TrialPilot is an open-source scenario simulator and command center for clinical trials that ships with its own validation package.**
Import a real trial (ClinicalTrials.gov ID or protocol PDF), flip design levers — remote monitoring, home visits, local labs,
on-demand drug supply, fewer visits or sites — and instantly see cost, site staff time, patient travel burden, timeline risk
and carbon, every number as a P10/P50/P90 range with a clickable provenance trail. A command center compares (simulated)
trial-system feeds against the plan, raises alerts and estimates whether each intervention actually worked. Everything is
backed by an append-only audit trail, e-signatures with no self-approval, and an auto-generated GxP validation package.

## Quick start

Requirements: Python 3.11+ with [uv](https://docs.astral.sh/uv/), Node 20+ with [pnpm](https://pnpm.io/), GNU make.

```bash
make install   # uv sync + pnpm install
make dev       # API on http://localhost:8000, web on http://localhost:5173
make test      # all Python + web tests
```

Or with Docker: `docker compose up` (API :8000, web :5173).

## Repository layout

| Path | What |
|---|---|
| `contracts/` | Shared pydantic models (source of truth) + generated JSON Schema and TypeScript types |
| `engine/` | Pure calculation engine (cost, staff time, patient burden, carbon, uncertainty) |
| `api/` | FastAPI backend |
| `web/` | React + Vite + TypeScript frontend |
| `validation/` | `tpv` validation toolkit and generated GxP package |
| `science/` | Reproduction of published trial carbon footprints |
| `data/params/` | Parameter library (every number sourced or marked as an assumption) — see `data/params/SCHEMA.md` |

## Licence

MIT — see [LICENSE](LICENSE). Third-party components: [THIRD_PARTY.md](THIRD_PARTY.md).
