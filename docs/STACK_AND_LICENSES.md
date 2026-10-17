# Stack, services, models and licences

Reconciled October 17, 2026 against tested code e5c386b and the final [THIRD_PARTY.md](../THIRD_PARTY.md). The backend inventory check found 0 items to review. The older direct-package metadata tables below are a discovery snapshot, not a replacement for the exact locked inventory. Local execution is verified; container/deployment notices remain unverified because Docker was unavailable.

## Python direct and build dependencies

Every third-party runtime, build and development declaration in the currently present package manifests is included. The version below is the PyPI release whose metadata was opened, **not a claim about the installed/resolved version**. Preserve exact installed distribution licence texts and bundled notices in a release. A generic BSD classifier still requires the exact resolved licence check.

| Package | Declared requirement | Used by | Metadata version checked | Licence metadata / evidence |
|---|---|---|---|---|
| anthropic | anthropic>=1.0 | api (runtime) | 1.15.0 | MIT ([PyPI](https://pypi.org/pypi/anthropic/1.15.0/json)); optional live extraction; actual source configuration disclosed below |
| argon2-cffi | argon2-cffi>=25.1.0 | api (runtime) | 25.1.0 | MIT ([PyPI](https://pypi.org/pypi/argon2-cffi/25.1.0/json)) |
| fastapi | fastapi>=0.115 | api (runtime) | 0.143.3 | MIT ([PyPI](https://pypi.org/pypi/fastapi/0.143.3/json)) |
| hatchling | hatchling | api (build), contracts (build), engine (build), validation (build) | 1.32.4 | MIT ([PyPI](https://pypi.org/pypi/hatchling/1.32.4/json)) |
| httpx | httpx>=0.27 | api (dev), api (runtime) | 0.28.1 | BSD-3-Clause ([PyPI](https://pypi.org/pypi/httpx/0.28.1/json)) |
| jsonschema | jsonschema>=4.22 | contracts (dev) | 4.26.0 | MIT ([PyPI](https://pypi.org/pypi/jsonschema/4.26.0/json)) |
| mcp | mcp>=2.3.0 | api (read-only MCP server) | 2.3.0 | MIT; final installed inventory in THIRD_PARTY.md |
| markdown | markdown>=3.11.1 | validation (runtime) | 3.11.1 | BSD-3-Clause ([PyPI](https://pypi.org/pypi/markdown/3.11.1/json)) |
| mypy | mypy>=1.11 | contracts (dev), engine (dev) | 2.4.0 | MIT ([PyPI](https://pypi.org/pypi/mypy/2.4.0/json)) |
| numpy | numpy>=1.26 | api (runtime), engine (runtime) | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 ([PyPI](https://pypi.org/pypi/numpy/2.5.4/json)) |
| pdfplumber | pdfplumber>=0.11 | api (runtime) | 0.11.10 | MIT License ([PyPI](https://pypi.org/pypi/pdfplumber/0.11.10/json)) |
| pydantic | pydantic>=2.7,<3 | api (runtime), contracts (runtime), engine (runtime) | 2.14.1 | MIT ([PyPI](https://pypi.org/pypi/pydantic/2.14.1/json)) |
| pydantic-settings | pydantic-settings>=2.4 | api (runtime) | 2.16.0 | MIT ([PyPI](https://pypi.org/pypi/pydantic-settings/2.16.0/json)) |
| pytest | pytest>=8.2 | api (dev), contracts (dev), engine (dev), validation (dev) | 9.1.1 | MIT ([PyPI](https://pypi.org/pypi/pytest/9.1.1/json)) |
| python-multipart | python-multipart>=0.0.9 | api (runtime) | 0.0.32 | Apache-2.0 ([PyPI](https://pypi.org/pypi/python-multipart/0.0.32/json)) |
| pyyaml | PyYAML>=6.0, pyyaml>=6.0 | api (runtime), contracts (runtime), validation (runtime) | 6.0.3 | MIT ([PyPI](https://pypi.org/pypi/pyyaml/6.0.3/json)) |
| reportlab | reportlab>=4.2 | api (runtime) | 5.0.1 | BSD license (see license.txt for details), Copyright (c) 2000-2025, ReportLab Inc. ([PyPI](https://pypi.org/pypi/reportlab/5.0.1/json)) |
| ruff | ruff>=0.6 | api (dev), contracts (dev), engine (dev), validation (dev) | 0.17.1 | MIT ([PyPI](https://pypi.org/pypi/ruff/0.17.1/json)) |
| sqlmodel | sqlmodel>=0.0.22 | api (runtime) | 0.0.48 | MIT ([PyPI](https://pypi.org/pypi/sqlmodel/0.0.48/json)) |
| sse-starlette | sse-starlette>=2.1 | api (runtime) | 3.5.0 | BSD-3-Clause ([PyPI](https://pypi.org/pypi/sse-starlette/3.5.0/json)) |
| types-pyyaml | types-PyYAML>=6.0 | contracts (dev) | 6.0.12.20260906 | Apache-2.0 ([PyPI](https://pypi.org/pypi/types-pyyaml/6.0.12.20260906/json)) |
| uvicorn | uvicorn[standard]>=0.30 | api (runtime) | 0.54.0 | BSD-3-Clause ([PyPI](https://pypi.org/pypi/uvicorn/0.54.0/json)) |

## Web direct dependencies and tooling

Observed package metadata was read from the installed `web/node_modules/<name>/package.json`. Font and data terms remain separately relevant.

| Package | Manifest range | Role | Installed metadata version | Licence |
|---|---|---|---|---|
| @fontsource-variable/inter | ^5.3.0 | runtime | 5.3.0 | OFL-1.1 |
| d3-geo | ^3.1.1 | runtime | 3.1.1 | ISC |
| react | ^18.3.1 | runtime | 18.3.1 | MIT |
| react-dom | ^18.3.1 | runtime | 18.3.1 | MIT |
| react-router-dom | ^6.30.6 | runtime | 6.30.6 | MIT |
| recharts | ^2.15.4 | runtime | 2.15.4 | MIT |
| topojson-client | ^3.1.0 | runtime | 3.1.0 | ISC |
| world-atlas | ^2.0.2 | runtime | 2.0.2 | ISC |
| @playwright/test | ^1.64.1 | development/build/test | 1.64.1 | Apache-2.0 |
| @testing-library/jest-dom | ^6.9.1 | development/build/test | 6.10.0 | MIT |
| @testing-library/react | ^16.3.3 | development/build/test | 16.3.3 | MIT |
| @testing-library/user-event | ^14.6.8 | development/build/test | 14.6.8 | MIT |
| @types/d3-geo | ^3.1.1 | development/build/test | 3.1.1 | MIT |
| @types/node | ^22.20.5 | development/build/test | 22.20.5 | MIT |
| @types/react | ^18.3.31 | development/build/test | 18.3.31 | MIT |
| @types/react-dom | ^18.3.7 | development/build/test | 18.3.7 | MIT |
| @types/topojson-client | ^3.1.5 | development/build/test | 3.1.5 | MIT |
| @types/topojson-specification | ^1.0.5 | development/build/test | 1.0.5 | MIT |
| @vitejs/plugin-react | ^4.7.0 | development/build/test | 4.7.0 | MIT |
| autoprefixer | ^10.6.1 | development/build/test | 10.6.1 | MIT |
| cross-env | ^7.0.3 | development/build/test | 7.0.3 | MIT |
| jsdom | ^25.0.1 | development/build/test | 25.0.1 | MIT |
| postcss | ^8.5.30 | development/build/test | 8.5.30 | MIT |
| tailwindcss | ^3.4.19 | development/build/test | 3.4.19 | MIT |
| typescript | ~5.8.3 | development/build/test | 5.8.3 | Apache-2.0 |
| vite | ^6.4.4 | development/build/test | 6.4.4 | MIT |
| vitest | ^3.2.7 | development/build/test | 3.2.7 | MIT |

## Runtime, APIs, models and datasets

| Item | Use / status | Licence or terms / verification |
|---|---|---|
| TrialPilot original packages and docs | Application, seeded triangular sampling, forecasting/supply and difference-in-differences implementation | [MIT](../LICENSE); method citations do not establish empirical accuracy |
| Python runtime | Python packages require 3.11+ | [PSF-2.0 and included notices](https://docs.python.org/3/license.html) |
| Node.js runtime | Web tooling, project brief requests Node 20+ | [Node.js licence and bundled notices](https://github.com/nodejs/node/blob/main/LICENSE); verify actual runtime version at packaging |
| SQLite | Embedded database, including Python sqlite3 compliance storage | [Public domain](https://www.sqlite.org/copyright.html) |
| uv | Python installation and project runner | MIT OR Apache-2.0, [opened PyPI metadata](https://pypi.org/pypi/uv/0.13.1/json); metadata version is not an installed-version assertion |
| pnpm | Web package manager | MIT, [opened npm metadata](https://registry.npmjs.org/pnpm/12.14.0); actual installed tool version may differ |
| GNU Make and Bash | Development orchestration | GNU tool licences apply; Bash GPL-3.0-or-later per [GNU](https://www.gnu.org/software/bash/); exact installed Make distribution licence remains to inspect |
| Docker Engine and Compose | Container build/start configuration, not executed; Docker unavailable | Engine Apache-2.0 per [Docker](https://docs.docker.com/engine/); exact Compose distribution notices pending; Docker Desktop has [separate terms](https://www.docker.com/legal/docker-terms-use/) |
| Caddy | Optional A5 deployment proxy | Apache-2.0, [project licence](https://github.com/caddyserver/caddy/blob/master/LICENSE); optional configured proxy, runtime not verified |
| ClinicalTrials.gov API v2 and cached records | Registry import; absent schedules remain assumptions | [Terms](https://clinicaltrials.gov/about-site/terms-conditions): credit ClinicalTrials.gov, keep current, date processed and identify modifications; A4/THIRD_PARTY records terms updated Jan 31, 2023; attachments may have separate copyrights (page recheck returned a JS shell) |
| GeoNames offline export | Index present; contains data from GeoNames (geonames.org), transformed as described in fixture README | [CC BY 4.0](https://www.geonames.org/about.html); attribution and modifications in data/fixtures/ctgov/geonames/README.md |
| Natural Earth via world-atlas | Offline country geometry; installed world-atlas README identifies Natural Earth data | Natural Earth [public domain](https://www.naturalearthdata.com/about/terms-of-use/); world-atlas wrapper ISC |
| Inter font via @fontsource-variable/inter | Self-hosted UI font | OFL-1.1 in installed package metadata; retain font licence |
| UK government GHG factors | DESNZ 2022/2025/2026 cell-cited factors in docs/sources.md | [GOV.UK reuse guidance](https://www.gov.uk/help/reuse-govuk-content), OGL where applicable, with third-party exceptions; final source ledger records OGL v3.0; no factor workbooks committed |
| Griffiths, Fox, Williamson / LCCT 2024 | Published method and CASPS/PRIMETIME references, distinct from our outputs | [Paper CC BY 4.0](https://pmc.ncbi.nlm.nih.gov/articles/PMC10823997/); cite source and identify modifications; final source ledger records the supplementary material terms; preserve attribution and identify adaptations |
| ASPE, Moore et al., FDA, Clinical Trials Arena | Linked problem context, not copied full documents | Publisher terms apply; factual summaries and citations in EVIDENCE.md, no blanket MIT claim |
| Synthetic operations and assumed visit templates | Demo inputs; label synthetic/assumption explicitly | Original team-created fixture content under repository MIT; no claim of real patient or sponsor data |
| Protocol PDFs and extraction evaluation corpus | cached protocol transcriptions and linked sponsor PDFs | Rights vary by document; link source, record consent/terms, do not assume registry hosting relicenses attachments |
| Optional extraction LLM / hosted provider | Anthropic SDK declared in API manifest; Anthropic Messages API; EXTRACT_MODEL environment setting, source default claude-opus-5-5; recording uses cached transcription, no live-provider accuracy run | SDK MIT does not license the hosted model; provider/model service terms remain separate; source default is not a verified live-model invocation; no model weights or default provider licence inferred |
| AI coding/documentation assistance | A11 documentation drafted with OpenAI Codex | Provider service terms, not an embedded open-source library; this task used OpenAI Codex for coding/docs and @oai/artifact-tool for the editable deck; no model weights redistributed |
| ISPE GAMP 5 and other validation references | Method references only, references in final validation package | Copyrighted; link permitted references, never commit the guide PDF or claim approval from its publisher |
| Commercial competitor pages / SMI letter | Linked comparison and roadmap context | Publisher terms; links and concise paraphrases only; no vendor asset or logo reuse implied |

## Final reconciliation and media

The exact application dependency inventory is [THIRD_PARTY.md](../THIRD_PARTY.md), verified byte-identical by the backend, with 0 review items. Preserve resolved license texts and transitive notices when packaging a release; local tests do not certify a future container supply chain. DfT National Travel Survey uses OGL v3.0; Ember annual grid and Australian NGA factors use CC BY 4.0, as recorded in the backend source ledger. Original MIT licensing does not relicense registry attachments, datasets, provider services, fonts or publications.

Final media consists of original application screen captures, native editable slide text/tables, and short source-attributed summaries; no vendor logos, full papers or sponsor PDFs are embedded. UI maps retain Natural Earth/world-atlas and GeoNames attribution. Slides use an installed Arial-family font selected by the presentation runtime and do not embed font files. The deck was generated with the bundled @oai/artifact-tool; its runtime is not redistributed.

The silent WebM was recorded using locked Playwright and existing Microsoft Edge, with Playwright's portable FFmpeg dependency downloaded only to an OS temporary directory. VP9 video is delivered; FFmpeg binaries are not redistributed. Captions are original text. A local HTML player displays captions without external scripts. These are authoring tools, not added application runtime dependencies.

No hosted model weights or provider credentials are shipped. Live extraction accuracy, provider availability in deployment, container license assembly and production authentication remain separate checks. The final recording uses no live model call and makes no human-approval claim.
