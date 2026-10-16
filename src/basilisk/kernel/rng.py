"""Seeded randomizer (§5.5).

Every random integer is derived from (master_seed, roll_counter, sub_index)
with HMAC-SHA256, so results are stateless, reproducible on any machine and
any Python version, and verifiable once the seed is published. The seed is
never written to the event log; only a commitment to it is.
"""

from __future__ import annotations

import hashlib
import hmac

_SPACE = 2**64


class Randomizer:
    def __init__(self, master_seed: str):
        if not master_seed:
            raise ValueError("master_seed must be non-empty")
        self._key = master_seed.encode("utf-8")

    def commitment(self) -> str:
        """Published at campaign start; the seed itself is published at campaign end."""
        return hashlib.sha256(b"tob-seed-commitment:" + self._key).hexdigest()

    def integer(self, counter: int, sub: int, lo: int, hi: int) -> int:
        """Uniform integer in [lo, hi] by rejection sampling (no modulo bias)."""
        span = hi - lo + 1
        if span < 1:
            raise ValueError(f"empty range [{lo}, {hi}]")
        limit = (_SPACE // span) * span
        attempt = 0
        while True:
            msg = f"{counter}:{sub}:{attempt}".encode("ascii")
            x = int.from_bytes(hmac.new(self._key, msg, hashlib.sha256).digest()[:8], "big")
            if x < limit:
                return lo + x % span
            attempt += 1

    def shuffle(self, counter: int, items: list) -> list:
        """Deterministic Fisher-Yates shuffle consuming one roll counter."""
        out = list(items)
        for i in range(len(out) - 1, 0, -1):
            j = self.integer(counter, i, 0, i)
            out[i], out[j] = out[j], out[i]
        return out


def verify_commitment(seed: str, commitment: str) -> bool:
    return Randomizer(seed).commitment() == commitment
