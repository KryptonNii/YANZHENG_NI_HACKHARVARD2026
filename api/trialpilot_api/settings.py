"""Runtime settings (pydantic-settings). Values come from the environment or the repo's `.env`.

Secrets never live here; `.env.example` (A1) lists the names only.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# api/trialpilot_api/settings.py -> the repo root is two levels above the package.
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), ".env"), extra="ignore", populate_by_name=True
    )

    demo_offline: bool = Field(
        default=False,
        validation_alias=AliasChoices("DEMO_OFFLINE", "TP_DEMO_OFFLINE"),
        description="No external network calls; every external dependency uses cached fixtures.",
    )
    repo_root: Path = Field(default=REPO_ROOT, validation_alias="TP_REPO_ROOT")
    data_dir: Path | None = Field(
        default=None,
        validation_alias="TP_DATA_DIR",
        description="Writable data directory (Docker volume); the SQLite file goes here.",
    )
    db_path: Path | None = Field(
        default=None,
        validation_alias="TP_DB_PATH",
        description="SQLite file. Default: $TP_DATA_DIR/trialpilot.sqlite, else "
        "<repo>/var/trialpilot.sqlite",
    )
    params_dir: Path | None = Field(default=None, validation_alias="TP_PARAMS_DIR")
    fixtures_dir: Path | None = Field(default=None, validation_alias="TP_FIXTURES_DIR")
    science_results_path: Path | None = Field(default=None, validation_alias="TP_SCIENCE_RESULTS")
    web_dist_dir: Path | None = Field(default=None, validation_alias="TP_WEB_DIST")
    cors_origins: str = Field(
        default=(
            "http://localhost:5173,http://127.0.0.1:5173,"
            "http://localhost:5178,http://127.0.0.1:5178"
        ),
        validation_alias="TP_CORS_ORIGINS",
        description="Comma-separated list of allowed browser origins (Vite dev servers).",
    )
    default_draws: int = Field(default=2000, ge=100, le=20000, validation_alias="TP_DEFAULT_DRAWS")
    max_draws: int = Field(default=20000, ge=100, validation_alias="TP_MAX_DRAWS")
    default_seed: int = Field(default=7, validation_alias="TP_DEFAULT_SEED")
    compute_cache_size: int = Field(default=256, ge=0, validation_alias="TP_COMPUTE_CACHE_SIZE")
    compute_concurrency: int = Field(
        default=2, ge=1, le=32, validation_alias="TP_COMPUTE_CONCURRENCY",
        description="Engine runs executing at once; further requests queue (X-Queue-Ms).",
    )
    log_level: str = Field(default="INFO", validation_alias="TP_LOG_LEVEL")
    log_json: bool = Field(default=True, validation_alias="TP_LOG_JSON")
    seed_fixture_designs: bool = Field(default=True, validation_alias="TP_SEED_FIXTURE_DESIGNS")
    mount_optional_routers: bool = Field(
        default=True,
        validation_alias="TP_MOUNT_OPTIONAL_ROUTERS",
        description="Mount A4/A6/A7 routers when importable (tests may switch this off).",
    )

    # ---- resolved paths -------------------------------------------------------------
    @property
    def resolved_db_path(self) -> Path:
        if self.db_path:
            return self.db_path
        return (self.data_dir or self.repo_root / "var") / "trialpilot.sqlite"

    @property
    def resolved_params_dir(self) -> Path:
        return self.params_dir or self.repo_root / "data" / "params"

    @property
    def resolved_fixtures_dir(self) -> Path:
        return self.fixtures_dir or self.repo_root / "data" / "fixtures"

    @property
    def resolved_science_results(self) -> Path:
        return self.science_results_path or self.repo_root / "science" / "out" / "results.json"

    @property
    def resolved_web_dist(self) -> Path:
        return self.web_dist_dir or self.repo_root / "web" / "dist"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
