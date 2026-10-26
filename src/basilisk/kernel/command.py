"""Command plumbing shared by the engine and its command mixins (§5.4, D-004).

`atomic` makes a command one transaction; `EngineError` is the error every
command raises; `_suggest` builds the "did you mean" message agents read.
"""

from __future__ import annotations

import copy
import difflib
import functools
import inspect
from typing import Any, Iterable

from . import dice, expr


class EngineError(ValueError):
    pass


def gm_call(options=None):
    """Log a GM-callable command as a `judgement_input` when a GM seat makes it
    (§2.13, D-044): control is the command's name, choice its arguments, options
    the list it was chosen from where the engine has one. Calls by the engine or
    the operator are not model choices and are not logged. Goes under `@atomic`,
    so a refused call logs nothing."""

    def deco(fn):
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(self, *args, **kwargs):
            bound = sig.bind(self, *args, **kwargs)
            bound.apply_defaults()
            by = bound.arguments.get("by") or self.gm_seat
            before = self.store.head(self.campaign_id)[0]
            result = fn(self, *args, **kwargs)
            if by not in ("engine", "operator") and self._role(by) == "gm":
                choice = {k: copy.deepcopy(v) for k, v in bound.arguments.items()
                          if k not in ("self", "by") and v is not None}
                after = self.store.head(self.campaign_id)[0]
                listed = options(self, bound.arguments) if options else None
                self._judge(by, fn.__name__, None, choice, listed, before + 1 if after > before else None)
            return result

        wrapper.gm_call = True  # read by the coverage test: every GM tool is logged
        return wrapper

    return deco


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
