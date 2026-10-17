"""OQ: configuration defaults and secrets handling."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SECRET_NAMES = ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "TP_SECRET_PEPPER")


def _env_example() -> dict[str, str]:
    values = {}
    for line in (REPO / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    return values


@pytest.mark.req("URS-029")
def test_documented_and_coded_offline_default_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    settings_mod = pytest.importorskip("trialpilot_api.settings")
    assert _env_example().get("DEMO_OFFLINE") == "0"
    monkeypatch.delenv("DEMO_OFFLINE", raising=False)
    monkeypatch.delenv("TP_DEMO_OFFLINE", raising=False)
    assert settings_mod.Settings(_env_file=None).demo_offline is False


@pytest.mark.req("URS-029")
def test_offline_switch_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    settings_mod = pytest.importorskip("trialpilot_api.settings")
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    assert settings_mod.Settings(_env_file=None).demo_offline is True


@pytest.mark.req("URS-030")
def test_env_example_lists_secret_names_without_values() -> None:
    values = _env_example()
    for name in SECRET_NAMES:
        assert name in values, f"{name} missing from .env.example"
        assert values[name] == "", f"{name} has a value in .env.example"


@pytest.mark.req("URS-030")
def test_env_file_is_ignored_and_not_tracked() -> None:
    ignored = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=REPO)
    assert ignored.returncode == 0, ".env is not git-ignored"
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", ".env"], cwd=REPO,
                             capture_output=True)
    assert tracked.returncode != 0, ".env is tracked by git"


@pytest.mark.req("URS-018", "URS-030")
def test_pin_pepper_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    from trialpilot_api.compliance import config

    monkeypatch.setenv("TP_SECRET_PEPPER", "from-env")
    assert config.pepper() == ("from-env", True)
