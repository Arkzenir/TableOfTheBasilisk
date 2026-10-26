"""The hook sandbox (T0.12; ARCHITECTURE §2.7; BUILD_PLAN P0.5)."""

import shutil
import textwrap

import pytest
import yaml

from basilisk.harness.scripted import verify
from basilisk.kernel import hooks
from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import PackError, resolve


def copy_packs(packs_dir, tmp_path):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    return dst


def with_hook(dst, source, point="resolution.step", name="probe", pack="lanternlight_hooked"):
    """Replace (or add) one hook in a pack copy."""
    path = dst / pack / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    data["hooks"] = [h for h in data.get("hooks") or [] if h["name"] != name] + [{"point": point, "name": name}]
    if point == "resolution.step":
        for proc in data["resolution"]["procedures"]:
            for step in proc["steps"]:
                if "hook" in step:
                    step["hook"] = name
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    (dst / pack / "hooks").mkdir(exist_ok=True)
    (dst / pack / "hooks" / f"{name}.py").write_text(textwrap.dedent(source))
    return resolve(pack, dst)


def table(pack, seed="hook-seed"):
    eng = Engine.start_campaign(pack, seed, {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    eng.start_session()
    eng.set_scene("test")
    return eng


def last(eng, kind):
    return [e["payload"] for e in eng.store.read(eng.campaign_id) if e["type"] == kind]


# ---------------------------------------------------------------- the shipped fixture

def test_natural_twenty_and_natural_one(packs_dir):
    pack = resolve("lanternlight_hooked", packs_dir)
    assert errors(lint(pack)) == [] and len(pack.get("hooks")) == 2
    seen = set()
    for i in range(300):
        eng = table(pack, f"nat-{i}")
        eng.commit_action("ash", "recall", gm={"difficulty": "extreme"})
        roll = last(eng, "roll_made")[-1]
        face = roll["groups"][0]["rolls"][0]
        outcome = last(eng, "procedure_resolved")[-1]["outcome"]
        ran = last(eng, "hook_ran")[-1]
        assert ran["hook"] == "natural" and ran["point"] == "resolution.step"
        if face == 20:
            assert outcome == "pass" and ran["result"] == {"outcome": "pass"}
            seen.add(20)
        elif face == 1:
            assert outcome == "fail" and ran["result"] == {"outcome": "fail"}
            seen.add(1)
        else:
            assert ran["result"] is None and outcome == ("pass" if roll["total"] >= 18 else "fail")
        if seen == {1, 20}:
            break
    assert seen == {1, 20}
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()


def test_sheet_validate_refuses_bad_characters(packs_dir, tmp_path):
    dst = copy_packs(packs_dir, tmp_path)
    pack = with_hook(dst, '''
        def hook(view, params, rng):
            if view["stats"]["might"] < 3:
                return ["might must be 3 or more"]
            return []
    ''', point="sheet.validate", name="standing")
    eng = Engine.start_campaign(pack, "s", {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    before = (eng.store.head(eng.campaign_id), hash_obj(eng.state))
    with pytest.raises(EngineError, match="breaks standing: might must be 3 or more"):
        eng.create_character("ash", "Ash", {"background": "soldier"})
    assert (eng.store.head(eng.campaign_id), hash_obj(eng.state)) == before


def test_source_is_pinned_with_the_pack(packs_dir, tmp_path):
    a = resolve("lanternlight_hooked", packs_dir)
    dst = copy_packs(packs_dir, tmp_path)
    path = dst / "lanternlight_hooked" / "hooks" / "natural.py"
    path.write_text(path.read_text() + "\n# a comment changes the source\n")
    b = resolve("lanternlight_hooked", dst)
    assert a.hash != b.hash and "def hook" in a.get("hooks")[0]["source"]


# ---------------------------------------------------------------- the contract at load

@pytest.mark.parametrize("source, fragment", [
    ("import time\ndef hook(view, params, rng):\n    return None\n", "Import is not allowed"),
    ("def hook(view, params, rng):\n    return open('x').read()\n", "'open' is not available"),
    ("def hook(view, params, rng):\n    return random.randint(1, 6)\n", "not .randint"),
    ("def hook(view, params, rng):\n    while True:\n        pass\n", "While is not allowed"),
    ("def hook(view, params, rng):\n    return {'total': 1.5}\n", "no floats"),
    ("def hook(view, params, rng):\n    return view.__class__\n", "may not start with '_'"),
    ("def hook(view, params, rng):\n    return getattr(view, 'x')\n", "'getattr' is not available"),
    ("def hook(view, params, rng):\n    return eval('1')\n", "'eval' is not available"),
    ("def hook(view, params, rng):\n    f = lambda: 1\n    return None\n", "Lambda is not allowed"),
    ("def hook(view, params, rng):\n    return view['total'] / 2\n", "use // for division"),
    ("def other(a):\n    return a\n", "exactly one function"),
    ("x = 1\nprint(x)\ndef hook(view, params, rng):\n    return None\n", "only the hook function and constants"),
])
def test_contract_violations_stop_the_pack_loading(packs_dir, tmp_path, source, fragment):
    dst = copy_packs(packs_dir, tmp_path)
    with pytest.raises(PackError, match="determinism contract") as e:
        with_hook(dst, source)
    assert fragment in str(e.value)


def test_unwired_unknown_and_missing_hooks(packs_dir, tmp_path):
    dst = copy_packs(packs_dir, tmp_path)
    with pytest.raises(PackError, match="reserved in this kernel build"):
        with_hook(dst, "def hook(view, params, rng):\n    return None\n", point="turn.order", name="order")
    dst2 = copy_packs(packs_dir, tmp_path / "b")
    with pytest.raises(PackError, match="unknown point"):
        with_hook(dst2, "def hook(view, params, rng):\n    return None\n", point="dice.magic", name="magic")
    dst3 = copy_packs(packs_dir, tmp_path / "c")
    (dst3 / "lanternlight_hooked" / "hooks" / "natural.py").unlink()
    with pytest.raises(PackError, match="unregistered hook 'natural'"):
        resolve("lanternlight_hooked", dst3)


# ---------------------------------------------------------------- the runtime

def test_draws_come_from_the_kernel_and_re_derive(packs_dir, tmp_path):
    dst = copy_packs(packs_dir, tmp_path)
    pack = with_hook(dst, '''
        def hook(view, params, rng):
            bonus = rng(1, 6) + rng(1, 6)
            return {"total": view["total"] + bonus}
    ''')
    eng = table(pack, "draw-seed")
    eng.commit_action("ash", "recall", gm={"difficulty": "hard"})
    draws = [p for p in last(eng, "roll_made") if p["expression"] == "hook"]
    assert len(draws) == 1 and len(draws[0]["draws"]) == 2
    resolved = last(eng, "procedure_resolved")[-1]
    base = [p for p in last(eng, "roll_made") if p["purpose"] == "procedure:check"][-1]["total"]
    assert resolved["total"] == base + draws[0]["total"]
    assert verify(eng.store, eng.campaign_id, pack, "draw-seed") == []


def test_hooks_cannot_touch_engine_state(packs_dir, tmp_path):
    dst = copy_packs(packs_dir, tmp_path)
    pack = with_hook(dst, '''
        def hook(view, params, rng):
            view["actor"]["might"] = 99
            view["scale"].append("victory")
            return None
    ''')
    eng = table(pack)
    might = eng.state["entities"]["ash"]["stats"]["might"]
    eng.commit_action("ash", "recall", gm={"difficulty": "easy"})
    assert eng.state["entities"]["ash"]["stats"]["might"] == might
    assert lantern_scale(pack) == ["fail", "pass"]


def lantern_scale(pack):
    return pack.by_id("resolution.outcome_scales")["pass_fail"]["ordered"]


def test_runaway_hooks_hit_the_step_limit_atomically(packs_dir, tmp_path):
    dst = copy_packs(packs_dir, tmp_path)
    pack = with_hook(dst, '''
        def hook(view, params, rng):
            n = 0
            for i in range(50000):
                n = n + 1
            return None
    ''')
    eng = table(pack)
    before = (eng.store.head(eng.campaign_id), hash_obj(eng.state))
    with pytest.raises(EngineError, match="exceeded"):
        eng.commit_action("ash", "recall", gm={"difficulty": "easy"})
    assert (eng.store.head(eng.campaign_id), hash_obj(eng.state)) == before


def test_bad_results_are_refused(packs_dir, tmp_path):
    dst = copy_packs(packs_dir, tmp_path)
    pack = with_hook(dst, "def hook(view, params, rng):\n    return {'outcome': 'victory'}\n")
    with pytest.raises(EngineError, match="No outcome 'victory'"):
        table(pack).commit_action("ash", "recall", gm={"difficulty": "easy"})


def test_every_hook_runs_twice_and_must_agree():
    hook = {"name": "flaky", "point": "resolution.step",
            "source": "def hook(view, params, rng):\n    return {'total': rng(1, 100)}\n"}
    calls = iter([5, 6])  # a randomizer that answers differently the second time
    with pytest.raises(hooks.HookError, match="not deterministic"):
        hooks.run(hook, {}, {}, lambda sub, lo, hi: next(calls))
    steady = iter([5, 5])
    assert hooks.run(hook, {}, {}, lambda sub, lo, hi: next(steady)) == ({"total": 5}, [[1, 100, 5]])


def test_hooked_procedures_cannot_be_peeked(packs_dir, tmp_path):
    dst = copy_packs(packs_dir, tmp_path)
    path = dst / "lanternlight_hooked" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    data["gm"]["fudgeable_procedures"] = ["check"]
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    eng = table(resolve("lanternlight_hooked", dst))
    with pytest.raises(EngineError, match="hook step cannot be peeked"):
        eng.commit_action("ash", "recall", gm={"difficulty": "easy", "peek": True})
