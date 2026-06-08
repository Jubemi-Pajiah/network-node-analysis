"""Nodal head correction solver (Newton-Raphson).

This module implements the complete Step 1 to Step 9 algorithm.
The unknowns are the junction heads H. For each pipe the flow
is recovered from the head difference; nodal continuity
gives the residual vector F(H); the sparse Jacobian J = dF/dH
is assembled and the linear system J dH = -F is solved
with scipy.sparse.linalg.spsolve (SuperLU). Heads are updated until the maximum
absolute continuity residual falls below the tolerance.

This is the single solver used both to produce the validation results and
by the Flask web application.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np
from scipy.sparse import csc_matrix
from scipy.sparse.linalg import spsolve

from .headloss import (
    DW, HW, G, NU_WATER, dw_resistance_from_flow, hw_resistance,
    model_exponent,
)
from .network import Network

# Numerical floor on |H_i - H_j| used only inside derivative evaluation, so the
# Jacobian stays finite when a pipe carries near-zero flow during early
# iterations. It does not affect the converged solution.
_DH_FLOOR = 1.0e-10


@dataclass
class SolveResult:
    """Container for every quantity required by the analysis and the app."""

    network_name: str
    model: str
    converged: bool
    iterations: int
    solve_time: float                      # wall-clock seconds
    tolerance: float
    max_iter: int

    heads: Dict[str, float] = field(default_factory=dict)          # H_j, m
    pressure_heads: Dict[str, float] = field(default_factory=dict)  # H_j - z_j, m
    flows: Dict[str, float] = field(default_factory=dict)          # Q_ij, m3/s
    velocities: Dict[str, float] = field(default_factory=dict)     # m/s
    head_losses: Dict[str, float] = field(default_factory=dict)    # m
    residual_history: List[float] = field(default_factory=list)    # max|F| per iter
    max_residual: float = float("nan")

    def summary(self) -> str:
        status = "converged" if self.converged else "DID NOT CONVERGE"
        return (f"[{self.network_name}] model={self.model} {status} in "
                f"{self.iterations} iterations, max|residual|={self.max_residual:.3e} "
                f"m3/s, solve time={self.solve_time*1000:.2f} ms")


def _pipe_resistance(pipe, model: str, flow: float) -> float:
    if model == HW:
        return hw_resistance(pipe.length, pipe.diameter, pipe.roughness)
    if model == DW:
        return dw_resistance_from_flow(pipe.length, pipe.diameter, pipe.roughness, flow)
    raise ValueError(f"unknown head-loss model '{model}'")


def solve_network(network: Network, model: str = HW, tol: float = 1e-6,
                  max_iter: int = 100) -> SolveResult:
    """Solve a pipe network by the nodal head correction method.

    Parameters
    ----------
    network : Network
        The network to solve. It is validated first; a NetworkError is raised
        for malformed input (no reservoir, disconnected node, bad geometry).
    model : str
        "H-W" for Hazen-Williams or "D-W" for Darcy-Weisbach.
    tol : float
        Convergence tolerance on the maximum absolute continuity residual
        (m3/s). Default 1e-6.
    max_iter : int
        Maximum number of iterations. Default 100.
    """
    network.validate()
    n = model_exponent(model)

    # ---- index the unknown (junction) nodes ------------------------------------
    junctions = network.junctions
    idx = {node.id: k for k, node in enumerate(junctions)}
    n_unknown = len(junctions)
    adj = network.neighbours()

    # current head of every node (reservoir heads are fixed) --------------------
    head = {nid: node.fixed_head if node.is_reservoir else 0.0
            for nid, node in network.nodes.items()}

    # Step 1: initialise unknown heads to the mean reservoir head
    mean_res = float(np.mean([r.fixed_head for r in network.reservoirs]))
    for node in junctions:
        head[node.id] = mean_res

    # cache of pipe resistance (constant for H-W; updated each iter for D-W)
    flow: Dict[str, float] = {p.id: 0.0 for p in network.pipes}

    residual_history: List[float] = []
    t0 = time.perf_counter()
    converged = False
    k = 0

    while k < max_iter:
        # Step 2: pipe flows from current heads
        K: Dict[str, float] = {}
        for pipe in network.pipes:
            kij = _pipe_resistance(pipe, model, flow[pipe.id])
            K[pipe.id] = kij
            dh = head[pipe.start] - head[pipe.end]
            q = math.copysign((abs(dh) / kij) ** (1.0 / n), dh)
            flow[pipe.id] = q

        # Step 3: continuity residual at each unknown node
        F = np.zeros(n_unknown)
        for node in junctions:
            j = idx[node.id]
            inflow = 0.0
            for _other, pipe, orient in adj[node.id]:
                inflow += orient * flow[pipe.id]
            F[j] = inflow - node.demand

        # Step 4: convergence check
        max_res = float(np.max(np.abs(F))) if n_unknown else 0.0
        residual_history.append(max_res)
        if max_res < tol:
            converged = True
            break

        # Step 5: assemble the sparse Jacobian J = dF/dH
        rows: List[int] = []
        cols: List[int] = []
        data: List[float] = []
        for pipe in network.pipes:
            dh = head[pipe.start] - head[pipe.end]
            dh_eff = max(abs(dh), _DH_FLOOR)
            kij = K[pipe.id]
            # g = dQ/d(dH) = (1/(n K)) |Q|^(1-n) >= 0
            g = (1.0 / (n * kij)) * (dh_eff / kij) ** ((1.0 - n) / n)
            a, b = pipe.start, pipe.end
            a_unknown = a in idx
            b_unknown = b in idx
            if a_unknown:
                ia = idx[a]
                rows.append(ia); cols.append(ia); data.append(-g)
            if b_unknown:
                ib = idx[b]
                rows.append(ib); cols.append(ib); data.append(-g)
            if a_unknown and b_unknown:
                rows.append(ia); cols.append(ib); data.append(g)
                rows.append(ib); cols.append(ia); data.append(g)

        J = csc_matrix((data, (rows, cols)), shape=(n_unknown, n_unknown))

        # Step 6: solve J dH = -F with the sparse SuperLU solver
        dH = spsolve(J, -F)
        dH = np.atleast_1d(dH)

        # Step 7: update nodal heads
        for node in junctions:
            head[node.id] += float(dH[idx[node.id]])

        # Step 8: increment iteration counter
        k += 1

    solve_time = time.perf_counter() - t0

    # one final flow evaluation so reported flows match the final heads --------
    for pipe in network.pipes:
        kij = _pipe_resistance(pipe, model, flow[pipe.id])
        dh = head[pipe.start] - head[pipe.end]
        flow[pipe.id] = math.copysign((abs(dh) / kij) ** (1.0 / n), dh)

    # Step 9: post-processing (pressure heads, velocities, head losses)
    result = SolveResult(
        network_name=network.name, model=model, converged=converged,
        iterations=k if converged else max_iter,
        solve_time=solve_time, tolerance=tol, max_iter=max_iter,
        residual_history=residual_history,
        max_residual=residual_history[-1] if residual_history else float("nan"),
    )
    for nid, node in network.nodes.items():
        result.heads[nid] = head[nid]
        result.pressure_heads[nid] = head[nid] - node.elevation
    for pipe in network.pipes:
        q = flow[pipe.id]
        area = math.pi * pipe.diameter ** 2 / 4.0
        result.flows[pipe.id] = q
        result.velocities[pipe.id] = abs(q) / area
        result.head_losses[pipe.id] = abs(head[pipe.start] - head[pipe.end])

    return result
