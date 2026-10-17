"""Library check: the paper's activity data x TrialPilot's parameter library, with uncertainty.

Each library parameter is sampled triangular(low, mid, high) with its own seeded stream (common random numbers
keyed by (seed, parameter id)), so results are deterministic and a parameter has the same draws everywhere.
"""

from __future__ import annotations

import ast
import operator
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import yaml
from numpy.typing import NDArray
from trialpilot_contracts import Parameter

FloatArray = NDArray[np.float64]
Kind = Literal["independent", "same_source"]


def triangular_draws(p: Parameter, seed: int, n: int) -> FloatArray:
    """Inverse-CDF triangular(low, mid, high) draws on a stream keyed by (seed, parameter id)."""
    lo, mode, hi = p.value_low, p.value_mid, p.value_high
    if hi == lo:
        return np.full(n, lo, dtype=np.float64)
    rng = np.random.default_rng([seed, zlib.crc32(p.id.encode("utf-8"))])
    u = rng.random(n)
    c = (mode - lo) / (hi - lo)
    left = lo + np.sqrt(u * (hi - lo) * (mode - lo))
    right = hi - np.sqrt((1 - u) * (hi - lo) * (hi - mode))
    return np.where(u < c, left, right)


_BINOPS: dict[type[ast.operator], Callable[[FloatArray, FloatArray], FloatArray]] = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
}


def evaluate(expr: str, env: Mapping[str, FloatArray | float]) -> FloatArray:
    """Evaluate `expr` (numbers, names from `env`, + - * /, unary minus, parentheses) — nothing else."""

    def ev(node: ast.AST) -> FloatArray:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return np.asarray(float(node.value))
        if isinstance(node, ast.Name):
            if node.id not in env:
                raise KeyError(f"unknown variable {node.id!r} in {expr!r}")
            return np.asarray(env[node.id], dtype=np.float64)
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            return _BINOPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        raise ValueError(f"unsupported syntax in factor expression {expr!r}")

    return np.asarray(ev(ast.parse(expr, mode="eval")), dtype=np.float64)


@dataclass(frozen=True)
class FactorSpec:
    key: str
    kind: Kind
    expr: str
    vars: dict[str, str]
    note: str = ""

    @property
    def parameter_ids(self) -> list[str]:
        return list(dict.fromkeys(self.vars.values()))


def load_factor_map(path: Path) -> dict[str, FactorSpec]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, FactorSpec] = {}
    for key, raw in doc.items():
        spec = FactorSpec(key=key, kind=raw["kind"], expr=raw["expr"], vars=dict(raw["vars"]),
                          note=str(raw.get("note", "")))
        names = {n.id for n in ast.walk(ast.parse(spec.expr, mode="eval")) if isinstance(n, ast.Name)}
        if names != set(spec.vars):
            raise ValueError(f"factor_map {key}: expr names {sorted(names)} != vars {sorted(spec.vars)}")
        out[key] = spec
    return out


@dataclass(frozen=True)
class LibraryFactor:
    """Draws of one paper factor's library equivalent, or why there is none."""

    key: str
    draws: FloatArray | None
    parameter_ids: list[str]
    missing: list[str]
    kind: Kind | None
    note: str

    @property
    def available(self) -> bool:
        return self.draws is not None


class LibrarySampler:
    """Caches parameter draws so every line that uses a parameter sees the same draws."""

    def __init__(self, params: Mapping[str, Parameter], factor_map: Mapping[str, FactorSpec],
                 seed: int, n: int) -> None:
        self.params = params
        self.factor_map = factor_map
        self.seed = seed
        self.n = n
        self._draws: dict[str, FloatArray] = {}

    def draws(self, pid: str) -> FloatArray:
        if pid not in self._draws:
            self._draws[pid] = triangular_draws(self.params[pid], self.seed, self.n)
        return self._draws[pid]

    def factor(self, key: str) -> LibraryFactor:
        spec = self.factor_map.get(key)
        if spec is None:
            return LibraryFactor(key, None, [], [], None, "no library equivalent; paper factor kept")
        missing = [pid for pid in spec.parameter_ids if pid not in self.params]
        if missing:
            return LibraryFactor(key, None, spec.parameter_ids, missing, spec.kind,
                                 f"library is missing {', '.join(missing)}; paper factor kept")
        env = {name: self.draws(pid) for name, pid in spec.vars.items()}
        values = np.broadcast_to(evaluate(spec.expr, env), (self.n,)).astype(np.float64)
        return LibraryFactor(key, values, spec.parameter_ids, [], spec.kind, spec.note)
