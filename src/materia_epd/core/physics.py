import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np
import structlog

from materia_epd.core.constants import (
    _REL_DEC,
    _TOL_ABS,
    _TOL_REL,
    ACCEPTED_RESCALINGS,
    ICONS,
    IDX_TO_NAME,
    NAME_TO_IDX,
    POTENTIAL_CORRECTIONS,
    QUANTITIES,
    REASONABLE_RANGES,
    REL,
    VARS,
)

logger = structlog.wrap_logger(logging.getLogger(__name__))


class RuleMode(str, Enum):
    PRODUCT = "product"
    DIVIDE = "divide"


@dataclass(frozen=True)
class Rule:
    target: int
    reqs: Tuple[int, ...]
    mode: RuleMode


def _build_rules(rel: List[Tuple[str, List[str]]]) -> List[Rule]:
    rules: List[Rule] = []
    for left, rights in rel:
        L = NAME_TO_IDX[left]
        R = tuple(NAME_TO_IDX[r] for r in rights)
        rules.append(Rule(L, R, RuleMode.PRODUCT))
        for i, r in enumerate(R):
            reqs = (L,) + tuple(x for j, x in enumerate(R) if j != i)
            rules.append(Rule(r, reqs, RuleMode.DIVIDE))
    rules = list(dict.fromkeys(rules))
    return rules


RULES: List[Rule] = _build_rules(REL)

RULES_BY_REQ: List[List[int]] = [[] for _ in VARS]

for k, ru in enumerate(RULES):
    for r in ru.reqs:
        RULES_BY_REQ[r].append(k)


def _is_close(a: float, b: float) -> bool:
    return np.isclose(a, b, rtol=_TOL_REL, atol=_TOL_ABS)


def _round(value: float, decimals: int = _REL_DEC) -> float:
    return round(value, decimals)


def check_properties_ranges(uuid: str, kwargs: Dict[str, Optional[float]]) -> None:
    for prop, value in kwargs.items():
        min_val, max_val = REASONABLE_RANGES[prop]
        if value is None:
            continue
        if not (min_val <= value <= max_val):
            logger.debug(
                f"Range warning {ICONS.WARNING}",
                uuid=uuid,
                message=f"{prop} {value} is outside "
                f"the expected range ({min_val}–{max_val}).",
            )
            if prop in POTENTIAL_CORRECTIONS.keys():
                value = value * POTENTIAL_CORRECTIONS[prop]["factor"]
                if min_val <= value <= max_val:
                    kwargs[prop] = value
                    logger.debug(
                        f"Unit conversion {ICONS.WARNING}",
                        uuid=uuid,
                        message=f"{prop} converted "
                        f"from {POTENTIAL_CORRECTIONS[prop]['from']} "
                        f"to {POTENTIAL_CORRECTIONS[prop]['to']}: {value}.",
                    )
    return kwargs


def _eval_rule(vals: List[Optional[float]], ru: Rule) -> Optional[float]:
    if any(vals[r] is None for r in ru.reqs):
        return None
    elif ru.mode is RuleMode.PRODUCT:
        return np.prod([float(vals[i]) for i in ru.reqs])
    elif ru.mode is RuleMode.DIVIDE:
        nom_idx, *denom_idxs = ru.reqs
        denom = np.prod([float(vals[i]) for i in denom_idxs], initial=1.0)
        if abs(denom) <= _TOL_ABS:
            return None
        return float(vals[nom_idx]) / denom


def _rule_log_coeffs(ru: Rule) -> Dict[int, float]:
    coeffs: Dict[int, float] = {ru.target: 1.0}
    if ru.mode is RuleMode.PRODUCT:
        for req in ru.reqs:
            coeffs[req] = coeffs.get(req, 0.0) - 1.0
    elif ru.mode is RuleMode.DIVIDE:
        num_idx, *denom_idxs = ru.reqs
        coeffs[num_idx] = coeffs.get(num_idx, 0.0) - 1.0
        for i in denom_idxs:
            coeffs[i] = coeffs.get(i, 0.0) + 1.0
    return coeffs


def _build_property_eq_system(
    adj_col: Dict[int, int],
) -> tuple[np.ndarray, np.ndarray]:
    rows: list[list[float]] = []
    for ru in RULES:
        coeffs = _rule_log_coeffs(ru)
        if not all(idx in adj_col for idx in coeffs.keys()):
            continue
        row = [0.0] * len(adj_col)
        for idx, c in coeffs.items():
            row[adj_col[idx]] += c
        if any(abs(x) > _TOL_ABS for x in row):
            if any(row == r or row == [-x for x in r] for r in rows):
                continue
            else:
                rows.append(row)
    A_eq = np.asarray(rows, dtype=float)
    b_eq = np.zeros(A_eq.shape[0], dtype=float)
    return A_eq, b_eq


def _project_logs_onto_eq(
    scaled_baseline: Dict[str, float],
    targets: Dict[str, float],
    internal_idxs: Dict[str, int],
) -> np.ndarray:
    adj_idxs = [NAME_TO_IDX[name] for name in VARS if scaled_baseline[name] is not None]
    adj_col = {idx: j for j, idx in enumerate(adj_idxs)}
    base_logs = np.array(
        [np.log(scaled_baseline[IDX_TO_NAME[idx]]) for idx in adj_idxs], dtype=float
    )
    weights = np.full(len(adj_idxs), float(1), dtype=float)
    A_eq, b_eq = _build_property_eq_system(adj_col)
    n_constraints = len(targets)
    W = np.diag(weights)
    E = np.zeros((len(base_logs), n_constraints))
    d = np.array([np.log(targets[key]) for key in targets], dtype=float)
    for j, key in enumerate(targets.keys()):
        E[internal_idxs[key], j] = 1
    n, r, c = len(base_logs), A_eq.shape[0], len(targets)

    K = np.block(
        [
            [2.0 * W, A_eq.T, E],
            [A_eq, np.zeros((r, r)), np.zeros((r, c))],
            [E.T, np.zeros((c, r)), np.zeros((c, c))],
        ]
    )

    rhs = np.concatenate([2.0 * W @ base_logs, b_eq, d])

    x = np.linalg.solve(K, rhs)
    return x[:n]


class Material:
    def __init__(self, **kwargs):
        for name in VARS:
            setattr(self, name, None)

        for k, v in kwargs.items():
            if k in VARS:
                setattr(self, k, None if v is None or v <= 0 else v)

        self._conflicts: List[Tuple[str, float, float, Tuple[str, ...]]] = []
        self.scaling_factor: float = 1.0
        self.initial_baseline: Dict[str, Optional[float]] = {}
        self.scaled_baseline: Dict[str, Optional[float]] = {}

    def to_dict(self) -> Dict[str, Optional[float]]:
        return {name: getattr(self, name) for name in VARS}

    def _compute(self) -> "Material":
        vals = [getattr(self, name) for name in VARS]
        known = [v is not None for v in vals]
        queue = [i for i, k in enumerate(known) if k]
        self._conflicts.clear()
        while queue:
            var_idx = queue.pop(0)
            for ru_idx in RULES_BY_REQ[var_idx]:
                ru = RULES[ru_idx]
                cand = _eval_rule(vals, ru)
                if cand is None:
                    continue
                if known[ru.target]:
                    if not _is_close(vals[ru.target], cand):
                        self._conflicts.append(
                            (
                                VARS[ru.target],
                                float(vals[ru.target]),
                                float(cand),
                                tuple(VARS[i] for i in ru.reqs),
                            )
                        )
                    continue
                vals[ru.target] = cand
                known[ru.target] = True
                setattr(self, VARS[ru.target], cand)
                queue.append(ru.target)

    def _clean(self, targets: Dict[str, float]) -> "Material":
        if self._conflicts is None:
            return self

        known_vars = [
            name for name in VARS if self.scaled_baseline.get(name) is not None
        ]
        internal_idxs = {name: i for i, name in enumerate(known_vars)}
        y = _project_logs_onto_eq(self.scaled_baseline, targets, internal_idxs)

        for name, idx in internal_idxs.items():
            setattr(self, name, _round(float(np.exp(y[idx]))))

        self._compute()
        if self._conflicts:
            msgs = [
                f"{n}: had {v0}, derived {v1} from {reqs}"
                for (n, v0, v1, reqs) in self._conflicts
            ]
            raise ValueError(
                "Inconsistent derived values (after projection):\n - "
                + "\n - ".join(msgs)
            )

    def rescale(self, targets: Dict[str, float]) -> "Material":
        targets = {k: v for k, v in targets.items() if v is not None}

        for field, value in targets.items():
            if field not in VARS:
                raise ValueError(f"Unknown field: {field}")
            if value is None or value <= 0:
                raise ValueError(f"Invalid value for {field}: {value}")

        if not any(set(targets.keys()) == combo for combo in ACCEPTED_RESCALINGS):
            raise ValueError(
                f"Invalid :{set(targets.keys())}. Must match {ACCEPTED_RESCALINGS}"
            )

        self.initial_baseline = self.to_dict()
        self._compute()

        for field, value in targets.items():
            initial_value = getattr(self, field)
            if initial_value is None or initial_value <= 0:
                raise ValueError(f"Cannot scale: '{field}' is {initial_value}")
            self.scaling_factor = _round(self.scaling_factor * value / initial_value)
            setattr(self, field, value)
            if field == "layer_thickness":
                if self.surface is None or self.surface <= 0:
                    raise ValueError(
                        "Cannot adjust thickness: surface must be known and > 0."
                    )
                if self.gross_density is None or self.gross_density <= 0:
                    raise ValueError(
                        "Cannot adjust thickness: density must be known and > 0."
                    )
                if self.grammage is not None:
                    setattr(
                        self,
                        "grammage",
                        getattr(self, "grammage") * value / initial_value,
                    )

        for name in QUANTITIES:
            if name not in targets.keys() and getattr(self, name) is not None:
                setattr(self, name, getattr(self, name) * self.scaling_factor)

        self.scaled_baseline = self.to_dict()
        self._clean(targets)
