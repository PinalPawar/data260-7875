"""
HW5 Part 3: timeouts, bounded exponential-backoff retries, and seeded
fault injection for the storage operations the tools depend on.

  RetryPolicy     -> how many attempts, how long to wait, how long is too long
  ResilientStore  -> wraps any store; every search/detail/stats call gets a
                     timeout and is retried on failure
  FlakyStore      -> wraps any store and makes it fail on purpose, either at
                     a seeded random rate or following a fixed script
"""
import random
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass


class TransientStorageError(Exception):
    """A temporary storage failure (the kind worth retrying)."""


class StorageUnavailable(Exception):
    """Raised after every allowed attempt failed. Tools turn this into {ok:false}."""


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3        # 1 first try + 2 retries
    timeout_s: float = 2.0       # each attempt may take at most this long
    base_delay_s: float = 0.1    # wait before retry 1; doubles each retry
    max_delay_s: float = 1.0     # ...but never longer than this (the "bound")

    def delay_before_retry(self, retry_number: int) -> float:
        """retry_number is 1 for the first retry: 0.1s, 0.2s, 0.4s ... capped."""
        return min(self.max_delay_s, self.base_delay_s * (2 ** (retry_number - 1)))


INTERACTIVE_POLICY = RetryPolicy()

_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="store-call")


class ResilientStore:
    """Adds a timeout + retry-with-backoff around every call to the wrapped store."""

    def __init__(self, store, policy: RetryPolicy = INTERACTIVE_POLICY, sleep=time.sleep):
        self._store = store
        self.policy = policy
        self._sleep = sleep
        self.last_call = {"attempts": 0, "errors": [], "waited_s": 0.0}

    def _call(self, method_name: str, *args):
        errors, waited = [], 0.0
        for attempt in range(1, self.policy.max_attempts + 1):
            future = _executor.submit(getattr(self._store, method_name), *args)
            try:
                result = future.result(timeout=self.policy.timeout_s)
                self.last_call = {"attempts": attempt, "errors": errors, "waited_s": waited}
                return result
            except FutureTimeout:
                future.cancel()
                errors.append(f"attempt {attempt}: timed out after {self.policy.timeout_s}s")
            except Exception as exc:
                errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
            if attempt < self.policy.max_attempts:
                delay = self.policy.delay_before_retry(attempt)
                waited += delay
                self._sleep(delay)
        self.last_call = {"attempts": self.policy.max_attempts, "errors": errors, "waited_s": waited}
        raise StorageUnavailable(f"gave up after {self.policy.max_attempts} attempts")

    def search(self, query, category, limit):
        return self._call("search", query, category, limit)

    def detail(self, notice_code):
        return self._call("detail", notice_code)

    def stats(self, group_by):
        return self._call("stats", group_by)


class FlakyStore:
    """
    Fault injection. Before passing a call to the real store it may fail on
    purpose:
      - failure_rate + seed: each attempt fails with that probability. The
        random generator is seeded, so the same seed always produces the same
        fail/succeed sequence.
      - script: a fixed list such as ["fail", "slow", "ok"], used one entry
        per attempt (for the three demonstrations). "slow" sleeps longer
        than the timeout.
    """

    def __init__(self, store, failure_rate: float = 0.0, seed: int = 0, script=None, slow_s: float = 0.0):
        self._store = store
        self._rate = failure_rate
        self._rng = random.Random(seed)
        self._script = list(script) if script else None
        self._slow_s = slow_s
        self.outcomes = []  # "ok" / "fail" / "slow", one per attempt, in order

    def _maybe_fail(self):
        if self._script is not None:
            step = self._script.pop(0) if self._script else "ok"
        else:
            step = "fail" if self._rng.random() < self._rate else "ok"
        self.outcomes.append(step)
        if step == "fail":
            raise TransientStorageError("injected failure")
        if step == "slow":
            time.sleep(self._slow_s)

    def search(self, query, category, limit):
        self._maybe_fail()
        return self._store.search(query, category, limit)

    def detail(self, notice_code):
        self._maybe_fail()
        return self._store.detail(notice_code)

    def stats(self, group_by):
        self._maybe_fail()
        return self._store.stats(group_by)
