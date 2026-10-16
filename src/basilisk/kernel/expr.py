"""Kernel expression language (§2.2).

Used for derived values, maxima, eligibility rules, tag derivations, and
derived difficulties. Integer-only, total, terminating, side-effect-free:
there are no loops, no assignments, no attribute access beyond reading from
context dictionaries, and only a handful of pure functions.

Allowed: integer and boolean literals, names and dotted names (actor.some_stat,
scene.some_flag, actor.conditions.some_condition), + - * // %, unary - and not, comparisons,
and/or, `a if c else b`, and the functions min, max, abs, clamp(x, lo, hi),
div(a, b) (division using the pack's rounding rule).
"""

from __future__ import annotations

import ast
from typing import Any

MAX_LEN = 500
MAX_NODES = 200
FUNCS = {"min", "max", "abs", "clamp", "div"}
ROUNDING = {"floor", "ceil", "half_up"}

_ALLOWED = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
    ast.Call, ast.Name, ast.Attribute, ast.Constant, ast.Load,
    ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod,
    ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
)


class ExprError(ValueError):
    pass


class Lenient(dict):
    """A context dict whose missing keys read as 0 (used for open-ended flags such as scene.*)."""

    def __missing__(self, key):
        return 0


_CACHE: dict[str, ast.Expression] = {}


def compile_expr(src: str) -> ast.Expression:
    if isinstance(src, bool) or isinstance(src, int):
        src = str(int(src))
    if src in _CACHE:
        return _CACHE[src]
    if len(src) > MAX_LEN:
        raise ExprError(f"expression longer than {MAX_LEN} chars")
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as e:
        raise ExprError(f"syntax error in {src!r}: {e.msg}") from None
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:
        raise ExprError("expression too complex")
    for node in nodes:
        if not isinstance(node, _ALLOWED):
            raise ExprError(f"{type(node).__name__} is not allowed in {src!r}")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, bool)):
            raise ExprError(f"only integer literals are allowed in {src!r}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS or node.keywords:
                raise ExprError(f"unknown function in {src!r}")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ExprError("names may not start with '_'")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ExprError("names may not start with '_'")
    _CACHE[src] = tree
    return tree


def names_used(src: str) -> set[str]:
    """Dotted names referenced by an expression, e.g. {'actor.some_stat', 'scene.some_flag'}."""
    tree = compile_expr(src)
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Name, ast.Attribute)):
            parts = []
            cur = node
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
                out.add(".".join(reversed(parts)))
    # keep only maximal chains
    return {n for n in out if not any(o != n and o.startswith(n + ".") for o in out)}


def _div(a: int, b: int, rounding: str) -> int:
    if b == 0:
        raise ExprError("division by zero")
    if b < 0:
        a, b = -a, -b
    if rounding == "floor":
        return a // b
    if rounding == "ceil":
        return -((-a) // b)
    return (2 * a + b) // (2 * b)  # half_up


def evaluate(src: str | int, ctx: dict[str, Any], rounding: str = "floor") -> int:
    if rounding not in ROUNDING:
        raise ExprError(f"unknown rounding {rounding!r}")
    tree = compile_expr(src if isinstance(src, str) else str(src))

    def as_int(v: Any) -> int:
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, int):
            return v
        raise ExprError(f"value {v!r} is not an integer")

    def ev(node) -> Any:
        if isinstance(node, ast.Expression):
            return as_int(ev(node.body))
        if isinstance(node, ast.Constant):
            return int(node.value)
        if isinstance(node, ast.Name):
            if node.id not in ctx:
                raise ExprError(f"unknown name {node.id!r}")
            return ctx[node.id]
        if isinstance(node, ast.Attribute):
            base = ev(node.value)
            if not isinstance(base, dict):
                raise ExprError(f"cannot read {node.attr!r} from a number")
            if node.attr in base or isinstance(base, Lenient):
                return base[node.attr]
            raise ExprError(f"unknown name {node.attr!r}")
        if isinstance(node, ast.UnaryOp):
            v = as_int(ev(node.operand))
            if isinstance(node.op, ast.USub):
                return -v
            if isinstance(node.op, ast.UAdd):
                return v
            return int(not v)
        if isinstance(node, ast.BinOp):
            a, b = as_int(ev(node.left)), as_int(ev(node.right))
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            if isinstance(node.op, ast.Mult):
                return a * b
            if b == 0:
                raise ExprError("division by zero")
            if isinstance(node.op, ast.FloorDiv):
                return a // b
            return a % b
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                for v in node.values:
                    if not as_int(ev(v)):
                        return 0
                return 1
            for v in node.values:
                if as_int(ev(v)):
                    return 1
            return 0
        if isinstance(node, ast.Compare):
            left = as_int(ev(node.left))
            for op, comp in zip(node.ops, node.comparators):
                right = as_int(ev(comp))
                ok = {
                    ast.Eq: left == right, ast.NotEq: left != right,
                    ast.Lt: left < right, ast.LtE: left <= right,
                    ast.Gt: left > right, ast.GtE: left >= right,
                }[type(op)]
                if not ok:
                    return 0
                left = right
            return 1
        if isinstance(node, ast.IfExp):
            return ev(node.body) if as_int(ev(node.test)) else ev(node.orelse)
        if isinstance(node, ast.Call):
            args = [as_int(ev(a)) for a in node.args]
            name = node.func.id
            if name == "min" and args:
                return min(args)
            if name == "max" and args:
                return max(args)
            if name == "abs" and len(args) == 1:
                return abs(args[0])
            if name == "clamp" and len(args) == 3:
                return max(args[1], min(args[2], args[0]))
            if name == "div" and len(args) == 2:
                return _div(args[0], args[1], rounding)
            raise ExprError(f"bad arguments to {name}()")
        raise ExprError(f"unsupported node {type(node).__name__}")

    return ev(tree)
