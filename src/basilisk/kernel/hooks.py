"""Pack hooks: the code escape hatch, sandboxed (§2.7, BUILD_PLAN P0.5).

A pack declares `hooks: [{point, name, version}]` and ships each one as
`hooks/<name>.py` beside its `pack.yaml`. The source is written in a small,
pure subset of Python and is enforced three ways (§2.7):

1. **Static check at load.** The module must define exactly one function,
   `def hook(view, params, rng):`, plus optional constant assignments. There are
   no imports, no `while`, no lambdas, classes, `try`, `with`, `global`, no
   floats, no `/` or `**`, no names or attributes beginning with `_`, and calls
   only to a whitelist of pure builtins, a few container methods, and `rng`. A
   hook that would read the clock, touch files or the network, or draw its own
   randomness cannot be written, so a pack that tries does not load.
2. **Sandboxed runtime.** The function runs with no builtins beyond the
   whitelist, on deep copies of its view and params (it cannot reach engine
   state), under a step limit. Randomness comes only from the `rng(lo, hi)`
   handle: the draws use one roll counter of the engine's randomizer and are
   logged as a `roll_made`, so they replay and re-derive from the seed.
3. **Run twice.** Every invocation runs a second time on fresh copies, with the
   same draws. Different results mean the hook is not deterministic, and the
   command is refused.

The source text is part of the resolved pack, so it is hashed and pinned with
it (§2.9). Wired points in this build: `resolution.step` (adjust a roll's
total or outcome) and `sheet.validate` (cross-field sheet constraints). The
other §2.7 points are reserved and refused at load until wired.
"""

from __future__ import annotations

import ast
import builtins
import copy
import sys
from pathlib import Path
from typing import Any, Callable

POINTS = ("dice.operator", "resolution.step", "effect.compound", "chargen.step", "turn.order",
          "tactical.score", "sheet.validate")
WIRED = ("resolution.step", "sheet.validate")
MAX_STEPS = 10_000  # Appendix C hook_runtime_limits.max_steps
MAX_SOURCE = 8_000  # characters
SAFE_BUILTINS = {
    "len": len, "min": min, "max": max, "abs": abs, "sum": sum, "sorted": sorted, "range": range,
    "list": list, "dict": dict, "int": int, "bool": bool, "str": str, "enumerate": enumerate, "zip": zip,
    "any": any, "all": all, "True": True, "False": False, "None": None,
}
SAFE_METHODS = {"get", "items", "keys", "values", "append", "extend", "count", "index", "startswith"}
_ALLOWED = (
    ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.Assign, ast.AugAssign, ast.If, ast.For,
    ast.Break, ast.Continue, ast.Pass, ast.Expr, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare, ast.IfExp,
    ast.Call, ast.keyword, ast.Name, ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.Set, ast.Subscript,
    ast.Slice, ast.Attribute, ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp, ast.comprehension,
    ast.Load, ast.Store, ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd, ast.Add, ast.Sub, ast.Mult, ast.FloorDiv,
    ast.Mod, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot,
    ast.JoinedStr, ast.FormattedValue,
)


class HookError(ValueError):
    pass


def check_source(name: str, source: str) -> list[str]:
    """Contract violations in a hook's source; empty means it may load."""
    if len(source) > MAX_SOURCE:
        return [f"hook {name}: source longer than {MAX_SOURCE} characters"]
    try:
        tree = ast.parse(source, filename=f"{name}.py")
    except SyntaxError as e:
        return [f"hook {name}: syntax error at line {e.lineno}: {e.msg}"]
    out: list[str] = []
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if len(functions) != 1 or functions[0].name != "hook" or \
            [a.arg for a in functions[0].args.args] != ["view", "params", "rng"]:
        out.append(f"hook {name}: must define exactly one function, def hook(view, params, rng)")
    for node in tree.body:
        is_doc = isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant)
        if not isinstance(node, (ast.FunctionDef, ast.Assign)) and not is_doc:
            out.append(f"hook {name} line {node.lineno}: only the hook function and constants may be top level")
    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if not isinstance(node, _ALLOWED):
            out.append(f"hook {name} line {line}: {type(node).__name__} is not allowed in a hook")
            continue
        if isinstance(node, ast.FunctionDef) and node is not (functions[0] if functions else None):
            out.append(f"hook {name} line {line}: nested functions are not allowed")
        if isinstance(node, ast.FunctionDef) and (node.decorator_list or node.args.defaults or node.args.vararg
                                                  or node.args.kwarg or node.args.kwonlyargs):
            out.append(f"hook {name} line {line}: the hook takes exactly (view, params, rng)")
        if isinstance(node, ast.Constant) and isinstance(node.value, (float, complex, bytes)):
            out.append(f"hook {name} line {line}: only integers, text, booleans and None (no floats)")
        if isinstance(node, ast.Name):
            if node.id.startswith("_"):
                out.append(f"hook {name} line {line}: names may not start with '_'")
            elif isinstance(node.ctx, ast.Load) and node.id not in SAFE_BUILTINS and node.id in dir(builtins):
                if node.id not in ("view", "params", "rng"):
                    out.append(f"hook {name} line {line}: {node.id!r} is not available in a hook")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                out.append(f"hook {name} line {line}: attributes may not start with '_'")
            elif node.attr not in SAFE_METHODS:
                out.append(f"hook {name} line {line}: only the methods {', '.join(sorted(SAFE_METHODS))} "
                           f"may be called, not .{node.attr}")
        if isinstance(node, ast.Call):
            fn = node.func
            ok = (isinstance(fn, ast.Name) and (fn.id in SAFE_BUILTINS or fn.id == "rng")) or \
                 (isinstance(fn, ast.Attribute) and fn.attr in SAFE_METHODS)
            if not ok:
                out.append(f"hook {name} line {line}: calls are limited to "
                           f"{', '.join(sorted(k for k in SAFE_BUILTINS if k[0].islower()))}, rng, and container methods")
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.Pow, ast.MatMult, ast.LShift,
                                                                 ast.RShift, ast.BitOr, ast.BitAnd, ast.BitXor)):
            out.append(f"hook {name} line {line}: use // for division; / and ** are not allowed")
    return list(dict.fromkeys(out))


def load(declared: list[dict], pack_dirs: dict[str, Path]) -> list[dict]:
    """Validate the hooks a resolved pack declares and attach their source.
    `pack_dirs` maps each hook name to the directory of the pack declaring it."""
    from .packs import PackError
    out = []
    for hook in declared:
        name = hook.get("name") if isinstance(hook, dict) else hook
        point = hook.get("point") if isinstance(hook, dict) else None
        path = pack_dirs.get(name, Path()) / "hooks" / f"{name}.py"
        if not name or name not in pack_dirs or not path.is_file():
            raise PackError(f"references unregistered hook {name!r}: no hooks/{name}.py beside the pack declaring it")
        if point not in POINTS:
            raise PackError(f"hook {name}: unknown point {point!r}; points: {', '.join(POINTS)}")
        if point not in WIRED:
            raise PackError(f"hook {name}: the {point} point is reserved in this kernel build; "
                            f"wired points: {', '.join(WIRED)}")
        source = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        problems = check_source(name, source)
        if problems:
            raise PackError("hook fails the determinism contract (§2.7): " + "; ".join(problems))
        out.append({"point": point, "name": name, "version": str(hook.get("version", "1")), "source": source})
    return sorted(out, key=lambda h: h["name"])


def _compile(name: str, source: str) -> Callable:
    namespace: dict[str, Any] = {"__builtins__": dict(SAFE_BUILTINS)}
    exec(compile(source, f"<hook {name}>", "exec"), namespace)  # noqa: S102 - statically checked above
    return namespace["hook"]


def _limited(fn: Callable, *args):
    steps = [0]

    def tracer(frame, event, arg):
        if event == "line":
            steps[0] += 1
            if steps[0] > MAX_STEPS:
                raise HookError(f"hook exceeded {MAX_STEPS} steps")
        return tracer

    previous = sys.gettrace()
    sys.settrace(tracer)
    try:
        return fn(*args)
    finally:
        sys.settrace(previous)


def run(hook: dict, view: dict, params: dict, draw: Callable[[int, int, int], int] | None) -> tuple[Any, list]:
    """Run a hook twice under the contract; return (result, draws). `draw(sub,
    lo, hi)` is the engine randomizer bound to one roll counter."""
    fn = _compile(hook["name"], hook["source"])
    results = []
    for _ in range(2):
        draws: list[list[int]] = []

        def rng(lo, hi, _draws=draws):
            if draw is None:
                raise HookError(f"hook {hook['name']}: no randomness at the {hook['point']} point")
            if isinstance(lo, bool) or isinstance(hi, bool) or not isinstance(lo, int) or not isinstance(hi, int) \
                    or lo > hi:
                raise HookError(f"hook {hook['name']}: rng(lo, hi) needs integers with lo <= hi")
            value = draw(len(_draws), lo, hi)
            _draws.append([lo, hi, value])
            return value

        try:
            result = _limited(fn, copy.deepcopy(view), copy.deepcopy(params), rng)
        except HookError:
            raise
        except Exception as e:  # noqa: BLE001 - any failure inside pack code is the hook's error
            raise HookError(f"hook {hook['name']} failed: {type(e).__name__}: {e}") from None
        results.append((copy.deepcopy(result), draws))
    if results[0] != results[1]:
        raise HookError(f"hook {hook['name']} is not deterministic: two runs on the same input disagreed")
    return results[0]
