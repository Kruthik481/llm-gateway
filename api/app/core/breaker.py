import time
from collections.abc import Callable
from typing import Literal

CircuitState = Literal["closed", "open", "half_open"]


class CircuitBreaker:
    """Per-provider breaker kept in process memory.

    shortcut: state lives in one process, correct while the API runs as a single instance;
    move it to Redis if the service is scaled out.
    """

    def __init__(
        self, threshold: int = 5, cooldown_s: float = 30.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._threshold = threshold
        self._cooldown_s = cooldown_s
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._trial_in_flight = False

    @property
    def state(self) -> CircuitState:
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at >= self._cooldown_s:
            return "half_open"
        return "open"

    def allow(self) -> bool:
        state = self.state
        if state == "closed":
            return True
        if state == "half_open" and not self._trial_in_flight:
            self._trial_in_flight = True
            return True
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._trial_in_flight = False

    def record_failure(self) -> None:
        self._trial_in_flight = False
        if self._opened_at is not None:
            self._opened_at = self._clock()  # a failed trial reopens for a full cooldown
            return
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = self._clock()
