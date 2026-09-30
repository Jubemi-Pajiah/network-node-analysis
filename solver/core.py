"""Nodal head correction solver (Newton-Raphson).

The unknowns are the junction heads H. For each pipe the flow is recovered
from the head difference; nodal continuity gives the residual vector F(H); the
sparse Jacobian J = dF/dH is assembled and the linear system J dH = -F is solved
with scipy.sparse.linalg.spsolve (SuperLU). Heads are updated until the maximum
absolute continuity residual falls below the tolerance.

This is the single solver used both by the analysis/validation scripts and by
the Flask web application.
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
from .network import Network, NetworkError

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


# Inner iteration that makes the Darcy-Weisbach friction factor consistent
# with the flow it produces. Convergence is geometric and takes a handful of
# passes; the cap only guards against a pathological pipe.
_DW_INNER_MAX = 25
_DW_INNER_TOL = 1e-12


def _pipe_resistance(pipe, model: str, flow: float) -> float:
    if model == HW:
        return hw_resistance(pipe.length, pipe.diameter, pipe.roughness)
    if model == DW:
        return dw_resistance_from_flow(pipe.length, pipe.diameter, pipe.roughness, flow)
    raise ValueError(f"unknown head-loss model '{model}'")



def _check_roughness_units(network: Network, model: str) -> None:
    """Reject a network whose roughness does not belong to the chosen model.

    Pipe.roughness carries the Hazen-Williams coefficient C under H-W and the
    absolute roughness epsilon in metres under D-W. The two differ by six orders
    of magnitude, so feeding one to the other produces a resistance that is
    wrong by a similar factor - and the solver still converges, to a confident
    and meaningless answer. Checking the magnitude turns that silent failure
    into an error at the point of use.
    """
    for pipe in network.pipes:
        if model == HW and pipe.roughness < 1.0:
            raise NetworkError(
                f"pipe {pipe.id} has roughness {pipe.roughness:g}, which looks "
                f"like a Darcy-Weisbach absolute roughness in metres, but the "
                f"Hazen-Williams model was requested (C is typically 80-150). "
                f"Build the network with model='{HW}' to get matching roughness.")
        if model == DW and pipe.roughness > 1.0:
            raise NetworkError(
                f"pipe {pipe.id} has roughness {pipe.roughness:g}, which looks "
                f"like a Hazen-Williams coefficient, but the Darcy-Weisbach "
                f"model was requested (epsilon is of order 1e-4 m). Build the "
                f"network with model='{DW}' to get matching roughness.")


def solve_network(network: Network, model: str = DW, tol: float = 1e-6,
                  max_iter: int = 100) -> SolveResult:
    """Solve a pipe network by the nodal head correction method.

    Parameters
    ----------
    network : Network
        The network to solve. It is validated first; a NetworkError is raised
        for malformed input (no reservoir, disconnected node, bad geometry).
    model : str
        "D-W" for Darcy-Weisbach (the default, and the model of record for this
        study) or "H-W" for Hazen-Williams. The default matches the one used by
        the network builders in solver.networks, because Pipe.roughness means
        different things under the two models and the two defaults must agree.
    tol : float
        Convergence tolerance on the maximum absolute continuity residual
        (m3/s). Default 1e-6.
    max_iter : int
        Maximum number of iterations. Default 100.
    """
    network.validate()
    _check_roughness_units(network, model)
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
            dh = head[pipe.start] - head[pipe.end]
            q = flow[pipe.id]
            kij = _pipe_resistance(pipe, model, q)

            if model == DW:
                # Under Darcy-Weisbach the resistance depends on the flow it is
                # used to compute, through the friction factor. Taking K from
                # the previous outer iteration leaves the two one step out of
                # step, and the continuity residual then zig-zags instead of
                # settling. Resolving the scalar relation dh = K(Q)|Q|Q for each
                # pipe first makes Q and f mutually consistent, so the outer
                # Newton iteration acts on a properly defined function of head.
                for _ in range(_DW_INNER_MAX):
                    q_next = math.copysign((abs(dh) / kij) ** (1.0 / n), dh)
                    converged_inner = abs(q_next - q) <= _DW_INNER_TOL * max(abs(q_next), 1e-12)
                    q = q_next
                    if converged_inner:
                        break
                    kij = _pipe_resistance(pipe, model, q)

            q = math.copysign((abs(dh) / kij) ** (1.0 / n), dh)
            K[pipe.id] = kij
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
