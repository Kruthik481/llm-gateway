import pytest
from pydantic import ValidationError

from app.settings import Settings

REQUIRED = {
    "database_url": "postgresql://u:p@localhost:5434/db",
    "redis_url": "redis://localhost:6380/0",
    "groq_api_key": "csk-test",
    "openrouter_api_key": "sk-or-test",
    "control_jwt_secret": "s" * 32,
    "metrics_token": "m" * 16,
    "web_origin": "http://localhost:3000",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in REQUIRED:
        monkeypatch.delenv(name.upper(), raising=False)


def test_defaults_match_the_spec() -> None:
    s = Settings(_env_file=None, **REQUIRED)
    assert s.rate_limit_per_minute == 20
    assert s.user_daily_tokens == 50_000
    assert s.global_daily_tokens == 1_000_000
    assert s.groq_base_url == "https://api.groq.com/openai/v1"
    assert s.openrouter_base_url == "https://openrouter.ai/api/v1"


def test_missing_required_values_fail_fast() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)
    assert {e["loc"][0] for e in exc.value.errors()} == set(REQUIRED)


def test_short_secrets_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**REQUIRED, "control_jwt_secret": "short"})
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**REQUIRED, "metrics_token": "short"})


def test_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name.upper(), value)
    assert Settings(_env_file=None).web_origin == "http://localhost:3000"
