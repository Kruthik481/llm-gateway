from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

PROVIDERS = ("groq", "openrouter")


@dataclass(frozen=True)
class Target:
    provider: str
    model: str


class Catalog:
    """Gateway model aliases mapped to the provider targets tried in order."""

    def __init__(self, routes: Mapping[str, tuple[Target, ...]]) -> None:
        self._routes = dict(routes)

    @classmethod
    def from_yaml(cls, path: Path, known_providers: Collection[str]) -> "Catalog":
        raw = yaml.safe_load(path.read_text()) or {}
        routes: dict[str, tuple[Target, ...]] = {}
        for alias, entries in raw.items():
            if not entries:
                raise ValueError(f"model alias {alias!r} has no targets")
            targets = tuple(Target(provider=str(e["provider"]), model=str(e["model"])) for e in entries)
            for target in targets:
                if target.provider not in known_providers:
                    raise ValueError(f"model alias {alias!r} uses unknown provider {target.provider!r}")
            routes[str(alias)] = targets
        return cls(routes)

    def targets(self, alias: str) -> tuple[Target, ...] | None:
        return self._routes.get(alias)

    def aliases(self) -> list[str]:
        return sorted(self._routes)
