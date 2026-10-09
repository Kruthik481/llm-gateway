from app.core.breaker import CircuitBreaker


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_opens_after_the_threshold_of_consecutive_failures() -> None:
    breaker = CircuitBreaker(threshold=3, cooldown_s=30, clock=Clock())
    for _ in range(2):
        breaker.record_failure()
    assert breaker.state == "closed"
    breaker.record_failure()
    assert breaker.state == "open"
    assert not breaker.allow()


def test_a_success_resets_the_failure_count() -> None:
    breaker = CircuitBreaker(threshold=2, clock=Clock())
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    assert breaker.state == "closed"


def test_half_open_lets_exactly_one_trial_through() -> None:
    clock = Clock()
    breaker = CircuitBreaker(threshold=1, cooldown_s=30, clock=clock)
    breaker.record_failure()
    clock.now += 30
    assert breaker.state == "half_open"
    assert breaker.allow()
    assert not breaker.allow()


def test_trial_success_closes_and_trial_failure_reopens() -> None:
    clock = Clock()
    breaker = CircuitBreaker(threshold=1, cooldown_s=30, clock=clock)
    breaker.record_failure()
    clock.now += 30
    breaker.allow()
    breaker.record_failure()
    assert breaker.state == "open"
    clock.now += 30
    breaker.allow()
    breaker.record_success()
    assert breaker.state == "closed"
    assert breaker.allow()
