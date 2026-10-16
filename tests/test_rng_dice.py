import pytest

from basilisk.kernel import dice
from basilisk.kernel.rng import Randomizer, verify_commitment


def test_same_seed_same_sequence():
    a, b = Randomizer("s"), Randomizer("s")
    assert [a.integer(i, 0, 1, 20) for i in range(200)] == [b.integer(i, 0, 1, 20) for i in range(200)]
    assert [Randomizer("t").integer(i, 0, 1, 20) for i in range(50)] != [a.integer(i, 0, 1, 20) for i in range(50)]


@pytest.mark.parametrize("sides", [4, 6, 8, 10, 12, 20, 100])
def test_distribution_10k(sides):
    r = Randomizer("dist")
    counts = [0] * sides
    for i in range(10_000):
        counts[r.integer(i, 0, 1, sides) - 1] += 1
    expected = 10_000 / sides
    chi2 = sum((c - expected) ** 2 / expected for c in counts)
    # generous bound: chi-square critical value at p=0.001 is below 2*df + 30 for these df
    assert chi2 < 2 * (sides - 1) + 30, counts


def test_commitment():
    assert verify_commitment("abc", Randomizer("abc").commitment())
    assert not verify_commitment("abd", Randomizer("abc").commitment())


def roll(src, seed="d", counter=0, **vars_):
    r = Randomizer(seed)
    return dice.evaluate(src, vars_, lambda sub, lo, hi: r.integer(counter, sub, lo, hi))


def test_dice_grammar_and_operators():
    assert dice.operators_used("2d20kh1 + {mod}") == {"sum", "keep"}
    assert dice.operators_used("6d10 count>=8") == {"sum", "count"}
    assert dice.operators_used("4dF") == {"fate"}
    assert dice.operators_used("1d6!") == {"sum", "explode"}
    assert roll("3 + 4 * 2").total == 11
    r = roll("2d20kh1")
    assert r.groups[0]["kept"] == [max(r.groups[0]["rolls"])]
    assert 0 <= roll("6d10 count>=8").total <= 6
    assert -4 <= roll("4dF").total <= 4
    assert roll("({n})d6", n=3).groups[0]["dice"] == "3d6"
    assert roll("-{spent}", spent=2).total == -2


def test_dice_errors_and_limits():
    for bad in ("2d", "d0", "1d6 +", "{x", "2x6"):
        with pytest.raises(dice.DiceError):
            dice.parse(bad)
    with pytest.raises(dice.DiceError):
        roll("{missing} + 1")
    assert dice.check_expression("2d20kh1", {"sum"}, 20, 100)  # keep not enabled
    assert dice.check_expression("1d1000", {"sum"}, 20, 100)
    assert not dice.check_expression("2d6 + {mod}", {"sum"}, 20, 100)


def test_value_range():
    assert dice.value_range("1d6") == (1, 6)
    assert dice.value_range("1d4 - 2") == (-1, 2)
    assert dice.value_range("2d6 + 1") == (3, 13)
    assert dice.value_range("1d6!") is None


def test_exploding_terminates():
    r = Randomizer("x")
    # force every die to max: explosion cap guarantees termination
    res = dice.evaluate("1d6!", {}, lambda sub, lo, hi: hi)
    assert len(res.groups[0]["rolls"]) == dice.EXPLODE_CAP + 1
