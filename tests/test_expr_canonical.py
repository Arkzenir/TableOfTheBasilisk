import pytest

from basilisk.kernel import expr
from basilisk.kernel.canonical import CanonicalError, canonical


def test_expressions():
    ctx = {"actor": {"a": 3, "conditions": expr.Lenient({"x": 1})}, "scene": expr.Lenient({"dim": 1})}
    assert expr.evaluate("10 + actor.a", ctx) == 13
    assert expr.evaluate("actor.conditions.x == 1 and scene.dim", ctx) == 1
    assert expr.evaluate("scene.unknown_flag", ctx) == 0
    assert expr.evaluate("clamp(actor.a * 5, 0, 10)", ctx) == 10
    assert expr.evaluate("5 if actor.a > 2 else 1", ctx) == 5


@pytest.mark.parametrize("rounding,expected", [("floor", 2), ("ceil", 3), ("half_up", 3)])
def test_rounding(rounding, expected):
    assert expr.evaluate("div(5, 2)", {}, rounding) == expected


@pytest.mark.parametrize("bad", ["__import__('os')", "actor.__class__", "[1,2]", "1.5", "'s'",
                                  "lambda: 1", "open('x')", "x := 1"])
def test_rejects_unsafe(bad):
    with pytest.raises(expr.ExprError):
        expr.evaluate(bad, {"actor": {}})


def test_canonical_refuses_floats():
    assert canonical({"b": 1, "a": [True, None, "x"]}) == '{"a":[true,null,"x"],"b":1}'
    with pytest.raises(CanonicalError):
        canonical({"x": 0.5})
