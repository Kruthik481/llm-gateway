from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import structlog
import yaml

log = structlog.get_logger()

_MILLION = Decimal(1_000_000)
_EIGHT_PLACES = Decimal("0.00000001")


@dataclass(frozen=True)
class Price:
    input_per_m: Decimal
    output_per_m: Decimal


class PriceBook:
    """List prices per `provider/model`, used to report what free-tier traffic would cost."""

    def __init__(self, prices: Mapping[str, Price]) -> None:
        self._prices = dict(prices)
        self._warned: set[str] = set()

    @classmethod
    def from_yaml(cls, path: Path) -> "PriceBook":
        raw = yaml.safe_load(path.read_text()) or {}
        return cls(
            {
                str(key): Price(Decimal(str(value["input"])), Decimal(str(value["output"])))
                for key, value in raw.items()
            }
        )

    def has(self, provider: str, model: str) -> bool:
        return f"{provider}/{model}" in self._prices

    def cost(self, provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
        key = f"{provider}/{model}"
        price = self._prices.get(key)
        if price is None:
            if key not in self._warned:
                self._warned.add(key)
                log.warning("price_missing", model=key)
            return Decimal(0)
        total = (price.input_per_m * prompt_tokens + price.output_per_m * completion_tokens) / _MILLION
        return total.quantize(_EIGHT_PLACES, rounding=ROUND_HALF_UP)
