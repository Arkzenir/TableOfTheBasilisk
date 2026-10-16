"""Command plumbing shared by the engine and its command mixins (§5.4, D-004).

`atomic` makes a command one transaction; `EngineError` is the error every
command raises; `_suggest` builds the "did you mean" message agents read.
"""

from __future__ import annotations

import copy
import difflib
import functools
from typing import Any, Iterable

from . import dice, expr


class EngineError(ValueError):
    pass


def atomic(fn):
    """Run a command as one transaction: on any error, no events are written and
    in-memory state is restored. A rejected command leaves no trace."""

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        if self._atomic_depth:
            return fn(self, *args, **kwargs)
        backup = copy.deepcopy(self.state)
        self.store.begin()
        self._atomic_depth += 1
        try:
            result = fn(self, *args, **kwargs)
        except BaseException as exc:
            self._atomic_depth -= 1
            self.store.rollback()
            self.state = backup
            # Indexes derived from state (e.g. canon) may describe the discarded state.
            self.__dict__.get("_derived_caches", {}).clear()
            if isinstance(exc, (expr.ExprError, dice.DiceError, KeyError)):
                raise EngineError(f"{type(exc).__name__}: {exc}") from exc
            raise
        self._atomic_depth -= 1
        self.store.commit()
        return result

    return wrapper


def _suggest(kind: str, wanted: Any, options: Iterable[str]) -> str:
    options = list(options)
    close = difflib.get_close_matches(str(wanted), options, n=1)
    hint = f" Did you mean {close[0]!r}?" if close else ""
    return f"No {kind} {wanted!r}.{hint} Available: {', '.join(sorted(options)) or 'none'}."
