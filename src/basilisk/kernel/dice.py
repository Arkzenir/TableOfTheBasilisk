"""Dice grammar (§2.4, §5.5).

Expressions are parsed to an AST, checked against the operators a pack enables,
and evaluated against the seeded randomizer. One evaluation consumes exactly one
roll counter; each die inside it uses a distinct sub-index.

Grammar:
    expr    := term (('+' | '-') term)*
    term    := factor ('*' factor)*
    factor  := '-' factor | primary [dice_suffix]
    primary := INT | '{' NAME '}' | '(' expr ')' | dice_suffix   (count defaults to 1)
    dice_suffix := 'd' (INT | 'F') modifier*
    modifier := 'kh' INT | 'kl' INT | '!' | 'count' ('>=' | '<=') INT

Operators (enabled per pack): sum, keep, explode, count, fate.
Arithmetic (+, -, *, constants, variables) is always available.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Callable

OPERATORS = {"sum", "keep", "explode", "count", "fate"}
EXPLODE_CAP = 10  # max extra dice per original die; guarantees termination


class DiceError(ValueError):
    pass


# ---------------------------------------------------------------- tokenizer

def tokenize(src: str) -> list[tuple[str, Any]]:
    toks: list[tuple[str, Any]] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
        elif c.isdigit():
            j = i
            while j < n and src[j].isdigit():
                j += 1
            toks.append(("INT", int(src[i:j])))
            i = j
        elif c == "{":
            j = src.find("}", i)
            if j < 0:
                raise DiceError(f"unclosed variable in {src!r}")
            name = src[i + 1 : j].strip()
            if not name.replace("_", "").replace(".", "").isalnum():
                raise DiceError(f"bad variable name {name!r}")
            toks.append(("VAR", name))
            i = j + 1
        elif src.startswith("count", i):
            toks.append(("COUNT", None))
            i += 5
        elif src.startswith("kh", i) or src.startswith("kl", i):
            toks.append(("KEEP", src[i + 1]))
            i += 2
        elif src.startswith(">=", i) or src.startswith("<=", i):
            toks.append(("CMP", src[i : i + 2]))
            i += 2
        elif c == "d":
            toks.append(("D", None))
            i += 1
        elif c == "F":
            toks.append(("F", None))
            i += 1
        elif c in "+-*()!":
            toks.append((c, None))
            i += 1
        else:
            raise DiceError(f"unexpected {c!r} at {i} in {src!r}")
    toks.append(("END", None))
    return toks


# ---------------------------------------------------------------- AST

@dataclass(frozen=True)
class Num:
    value: int


@dataclass(frozen=True)
class Var:
    name: str


@dataclass(frozen=True)
class Neg:
    operand: Any


@dataclass(frozen=True)
class Bin:
    op: str
    left: Any
    right: Any


@dataclass(frozen=True)
class Dice:
    count: Any
    sides: int | str  # int or "F"
    keep: tuple[str, int] | None = None
    explode: bool = False
    count_mode: tuple[str, int] | None = None


class _Parser:
    def __init__(self, src: str):
        self.src = src
        self.toks = tokenize(src)
        self.pos = 0

    def peek(self) -> str:
        return self.toks[self.pos][0]

    def take(self, kind: str | None = None):
        tok = self.toks[self.pos]
        if kind and tok[0] != kind:
            raise DiceError(f"expected {kind}, got {tok[0]} in {self.src!r}")
        self.pos += 1
        return tok

    def parse(self):
        node = self.expr()
        if self.peek() != "END":
            raise DiceError(f"trailing input in {self.src!r}")
        return node

    def expr(self):
        node = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()[0]
            node = Bin(op, node, self.term())
        return node

    def term(self):
        node = self.factor()
        while self.peek() == "*":
            self.take()
            node = Bin("*", node, self.factor())
        return node

    def factor(self):
        if self.peek() == "-":
            self.take()
            return Neg(self.factor())
        if self.peek() == "D":
            return self.dice_suffix(Num(1))
        kind = self.peek()
        if kind == "INT":
            node = Num(self.take()[1])
        elif kind == "VAR":
            node = Var(self.take()[1])
        elif kind == "(":
            self.take()
            node = self.expr()
            self.take(")")
        else:
            raise DiceError(f"unexpected {kind} in {self.src!r}")
        if self.peek() == "D":
            return self.dice_suffix(node)
        return node

    def dice_suffix(self, count):
        self.take("D")
        if self.peek() == "F":
            self.take()
            sides: int | str = "F"
        else:
            sides = self.take("INT")[1]
            if sides < 1:
                raise DiceError("dice need at least one side")
        keep = None
        explode = False
        count_mode = None
        while self.peek() in ("KEEP", "!", "COUNT"):
            kind = self.peek()
            if kind == "KEEP":
                which = self.take()[1]
                keep = ("h" if which == "h" else "l", self.take("INT")[1])
            elif kind == "!":
                self.take()
                explode = True
            else:
                self.take()
                cmp = self.take("CMP")[1]
                count_mode = (cmp, self.take("INT")[1])
        return Dice(count, sides, keep, explode, count_mode)


_CACHE: dict[str, Any] = {}


def parse(src: str):
    if src not in _CACHE:
        if len(src) > 200:
            raise DiceError("expression too long")
        _CACHE[src] = _Parser(src).parse()
    return _CACHE[src]


# ---------------------------------------------------------------- analysis

def _walk(node):
    yield node
    if isinstance(node, Neg):
        yield from _walk(node.operand)
    elif isinstance(node, Bin):
        yield from _walk(node.left)
        yield from _walk(node.right)
    elif isinstance(node, Dice):
        yield from _walk(node.count)


def operators_used(src: str) -> set[str]:
    used: set[str] = set()
    for node in _walk(parse(src)):
        if isinstance(node, Dice):
            used.add("fate" if node.sides == "F" else "sum")
            if node.keep:
                used.add("keep")
            if node.explode:
                used.add("explode")
            if node.count_mode:
                used.add("count")
    return used


def variables_used(src: str) -> set[str]:
    return {n.name for n in _walk(parse(src)) if isinstance(n, Var)}


def has_dice(src: str) -> bool:
    return any(isinstance(n, Dice) for n in _walk(parse(src)))


def check_expression(src: str, enabled: set[str], max_dice: int, max_sides: int) -> list[str]:
    """Problems with an expression under a pack's grammar settings (empty list = fine)."""
    try:
        tree = parse(src)
    except DiceError as e:
        return [str(e)]
    problems = []
    extra = operators_used(src) - set(enabled)
    if extra:
        problems.append(f"{src!r} uses operators not enabled by the pack: {sorted(extra)}")
    for node in _walk(tree):
        if isinstance(node, Dice):
            if isinstance(node.sides, int) and node.sides > max_sides:
                problems.append(f"{src!r}: d{node.sides} exceeds max_sides {max_sides}")
            if isinstance(node.count, Num) and node.count.value > max_dice:
                problems.append(f"{src!r}: {node.count.value} dice exceeds max_dice {max_dice}")
    return problems


ENUMERATION_LIMIT = 200_000  # outcomes enumerated for keep-highest/lowest before giving up


def distribution(src: str, variables: dict[str, int] | None = None) -> dict[int, Fraction] | None:
    """Exact probability of every total, as fractions summing to 1 (§2.10 property
    tests). None when no finite exact answer exists: exploding dice, or a keep
    over more combinations than `ENUMERATION_LIMIT`."""
    variables = dict(variables or {})

    def combine(a, b, fn):
        out: dict[int, Fraction] = {}
        for x, px in a.items():
            for y, py in b.items():
                v = fn(x, y)
                out[v] = out.get(v, Fraction(0)) + px * py
        return out

    def faces(node) -> list[int]:
        return [-1, 0, 1] if node.sides == "F" else list(range(1, node.sides + 1))

    def group(node, n: int):
        fs = faces(node)
        if node.keep is None:
            per = {}
            for f in fs:
                v = 1 if node.count_mode and (f >= node.count_mode[1] if node.count_mode[0] == ">=" else f <= node.count_mode[1])                     else (0 if node.count_mode else f)
                per[v] = per.get(v, Fraction(0)) + Fraction(1, len(fs))
            out = {0: Fraction(1)}
            for _ in range(n):
                out = combine(out, per, lambda x, y: x + y)
            return out
        if len(fs) ** n > ENUMERATION_LIMIT:
            return None
        which, k = node.keep
        out: dict[int, Fraction] = {}
        weight = Fraction(1, len(fs) ** n)
        for rolls in itertools.product(fs, repeat=n):
            kept = sorted(rolls, reverse=(which == "h"))[:k]
            if node.count_mode:
                cmp, target = node.count_mode
                v = sum(1 for r in kept if (r >= target if cmp == ">=" else r <= target))
            else:
                v = sum(kept)
            out[v] = out.get(v, Fraction(0)) + weight
        return out

    def dist(node):
        if isinstance(node, Num):
            return {node.value: Fraction(1)}
        if isinstance(node, Var):
            if node.name not in variables:
                raise DiceError(f"unbound variable {{{node.name}}} in {src!r}")
            return {int(variables[node.name]): Fraction(1)}
        if isinstance(node, Neg):
            inner = dist(node.operand)
            return None if inner is None else {-v: p for v, p in inner.items()}
        if isinstance(node, Bin):
            a, b = dist(node.left), dist(node.right)
            if a is None or b is None:
                return None
            fn = (lambda x, y: x + y) if node.op == "+" else (lambda x, y: x - y) if node.op == "-" else (lambda x, y: x * y)
            return combine(a, b, fn)
        if isinstance(node, Dice):
            if node.explode:
                return None
            counts = dist(node.count)
            if counts is None:
                return None
            out: dict[int, Fraction] = {}
            for n, pn in counts.items():
                g = group(node, max(n, 0))
                if g is None:
                    return None
                for v, pv in g.items():
                    out[v] = out.get(v, Fraction(0)) + pn * pv
            return out
        raise DiceError(f"unknown node {node!r}")

    return dist(parse(src))


def value_range(src: str, variables: dict[str, tuple[int, int]] | None = None) -> tuple[int, int] | None:
    """Exact [min, max] of an expression, or None if unbounded (exploding dice)."""
    variables = variables or {}

    def rng(node) -> tuple[int, int] | None:
        if isinstance(node, Num):
            return node.value, node.value
        if isinstance(node, Var):
            return variables.get(node.name, (0, 0))
        if isinstance(node, Neg):
            r = rng(node.operand)
            return None if r is None else (-r[1], -r[0])
        if isinstance(node, Bin):
            a, b = rng(node.left), rng(node.right)
            if a is None or b is None:
                return None
            if node.op == "+":
                return a[0] + b[0], a[1] + b[1]
            if node.op == "-":
                return a[0] - b[1], a[1] - b[0]
            prods = [x * y for x in a for y in b]
            return min(prods), max(prods)
        if isinstance(node, Dice):
            if node.explode:
                return None
            c = rng(node.count)
            if c is None:
                return None
            lo_n, hi_n = max(c[0], 0), max(c[1], 0)
            lo_face, hi_face = (-1, 1) if node.sides == "F" else (1, node.sides)
            kept_lo = min(node.keep[1], lo_n) if node.keep else lo_n
            kept_hi = min(node.keep[1], hi_n) if node.keep else hi_n
            if node.count_mode:
                return 0, hi_n
            lo = min(kept_lo * lo_face, kept_hi * lo_face)
            hi = max(kept_lo * hi_face, kept_hi * hi_face)
            return lo, hi
        raise DiceError(f"unknown node {node!r}")

    return rng(parse(src))


# ---------------------------------------------------------------- evaluation

@dataclass
class RollResult:
    expression: str
    total: int
    groups: list[dict] = field(default_factory=list)
    variables: dict[str, int] = field(default_factory=dict)
    dice_rolled: int = 0

    def to_payload(self) -> dict:
        return {
            "expression": self.expression,
            "total": self.total,
            "groups": self.groups,
            "variables": self.variables,
        }


def evaluate(
    src: str,
    variables: dict[str, int] | None = None,
    draw: Callable[[int, int, int], int] | None = None,
    max_dice: int = 100,
) -> RollResult:
    """Evaluate `src`. `draw(sub, lo, hi)` supplies random integers; it may be None
    only for expressions without dice."""
    variables = dict(variables or {})
    tree = parse(src)
    result = RollResult(expression=src, total=0)
    used_vars = {}
    sub = [0]

    def next_die(lo: int, hi: int) -> int:
        if draw is None:
            raise DiceError(f"{src!r} rolls dice but no randomizer was supplied")
        v = draw(sub[0], lo, hi)
        sub[0] += 1
        result.dice_rolled += 1
        if result.dice_rolled > max_dice * (EXPLODE_CAP + 1):
            raise DiceError("dice limit exceeded")
        return v

    def ev(node) -> int:
        if isinstance(node, Num):
            return node.value
        if isinstance(node, Var):
            if node.name not in variables:
                raise DiceError(f"unbound variable {{{node.name}}} in {src!r}")
            val = variables[node.name]
            if not isinstance(val, int) or isinstance(val, bool):
                raise DiceError(f"variable {node.name} must be an integer")
            used_vars[node.name] = val
            return val
        if isinstance(node, Neg):
            return -ev(node.operand)
        if isinstance(node, Bin):
            a, b = ev(node.left), ev(node.right)
            return a + b if node.op == "+" else a - b if node.op == "-" else a * b
        if isinstance(node, Dice):
            n = ev(node.count)
            if n < 0:
                raise DiceError("negative dice count")
            if n > max_dice:
                raise DiceError(f"{n} dice exceeds limit {max_dice}")
            lo, hi = (-1, 1) if node.sides == "F" else (1, node.sides)
            rolls = []
            for _ in range(n):
                v = next_die(lo, hi)
                rolls.append(v)
                extra = 0
                while node.explode and v == hi and extra < EXPLODE_CAP:
                    v = next_die(lo, hi)
                    rolls.append(v)
                    extra += 1
            kept = list(rolls)
            if node.keep:
                which, k = node.keep
                kept = sorted(rolls, reverse=(which == "h"))[:k]
            if node.count_mode:
                cmp, target = node.count_mode
                value = sum(1 for r in kept if (r >= target if cmp == ">=" else r <= target))
            else:
                value = sum(kept)
            sides_label = "F" if node.sides == "F" else str(node.sides)
            result.groups.append(
                {"dice": f"{n}d{sides_label}", "rolls": rolls, "kept": kept, "value": value}
            )
            return value
        raise DiceError(f"unknown node {node!r}")

    result.total = ev(tree)
    result.variables = used_vars
    return result
