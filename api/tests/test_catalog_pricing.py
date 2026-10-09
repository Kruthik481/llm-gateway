from decimal import Decimal
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from app.core.catalog import PROVIDERS, Catalog, Target
from app.core.pricing import Price, PriceBook

API_DIR = Path(__file__).resolve().parents[1]


def test_catalog_loads_ordered_targets() -> None:
    catalog = Catalog.from_yaml(API_DIR / "models.yaml", PROVIDERS)
    targets = catalog.targets("llama-3.3-70b")
    assert targets is not None
    assert [t.provider for t in targets] == ["cerebras", "openrouter"]
    assert catalog.targets("gpt-5") is None
    assert catalog.aliases() == sorted(catalog.aliases())


def test_catalog_rejects_unknown_providers(tmp_path: Path) -> None:
    path = tmp_path / "models.yaml"
    path.write_text("m:\n  - { provider: nope, model: x }\n")
    with pytest.raises(ValueError, match="nope"):
        Catalog.from_yaml(path, PROVIDERS)


def test_catalog_rejects_empty_routes(tmp_path: Path) -> None:
    path = tmp_path / "models.yaml"
    path.write_text("m: []\n")
    with pytest.raises(ValueError, match="no targets"):
        Catalog.from_yaml(path, PROVIDERS)


def test_every_catalog_target_has_a_price() -> None:
    catalog = Catalog.from_yaml(API_DIR / "models.yaml", PROVIDERS)
    book = PriceBook.from_yaml(API_DIR / "pricing.yaml")
    for alias in catalog.aliases():
        for target in catalog.targets(alias) or ():
            assert book.has(target.provider, target.model), f"{target} has no price"


def test_cost_is_exact_decimal() -> None:
    book = PriceBook({"cerebras/m": Price(Decimal("0.85"), Decimal("1.20"))})
    assert book.cost("cerebras", "m", 1_000, 500) == Decimal("0.00145000")
    assert book.cost("cerebras", "m", 1, 1) == Decimal("0.00000205")


def test_unknown_models_cost_zero_and_warn_once() -> None:
    book = PriceBook({})
    with capture_logs() as logs:
        assert book.cost("cerebras", "mystery", 10, 10) == Decimal(0)
        book.cost("cerebras", "mystery", 10, 10)
    assert [entry["event"] for entry in logs] == ["price_missing"]


def test_target_is_hashable_value() -> None:
    assert Target("cerebras", "m") == Target("cerebras", "m")
