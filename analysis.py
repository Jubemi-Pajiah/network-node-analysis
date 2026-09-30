"""Central analysis backbone.

Runs the solver and EPANET on all three networks, builds every comparison
table, measures computational performance, and caches the complete set of
numbers to results/results.json. The validation script and the figure
generator both read from this single source so that every reported number
traces to real solver or EPANET output.
"""

from __future__ import annotations

import json
import os
import time
from statistics import median
from typing import Dict, List

import numpy as np

from solver import (DW, HW, loop_network, large_network, medium_network,
                    solve_network)
from solver.networks import EPSILON_CAST_IRON, _grid_network
from validation.epanet_bridge import run_epanet

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

NETWORK_BUILDERS = [
    ("Single-loop network", loop_network),
    ("Medium grid network", medium_network),
    ("Large grid network", large_network),
]


def _timed_solve(build, model: str = DW, repeats: int = 5):
    """Solve repeatedly and keep the run with the median wall-clock time."""
    runs = []
    for _ in range(repeats):
        net = build()
        runs.append(solve_network(net, model=model))
    times = [r.solve_time for r in runs]
    med = median(times)
    best = min(runs, key=lambda r: abs(r.solve_time - med))
    return best


def _compare(network, result, epanet_heads, epanet_flows) -> Dict:
    """Build node-head and pipe-flow comparison tables and error metrics."""
    node_rows: List[Dict] = []
    max_head_pe = 0.0
    max_head_node = None
    for nid, node in network.nodes.items():
        if node.is_reservoir:
            continue
        mine = result.heads[nid]
        ep = epanet_heads[nid]
        ae = abs(mine - ep)
        pe = ae / abs(ep) * 100.0 if ep != 0 else 0.0
        node_rows.append({"node": nid, "mine": mine, "epanet": ep,
                          "abs_err": ae, "pct_err": pe})
        if pe > max_head_pe:
            max_head_pe = pe
            max_head_node = nid

    qmax = max(abs(v) for v in epanet_flows.values())
    pipe_rows: List[Dict] = []
    max_flow_pe = 0.0
    max_flow_pipe = None
    for pipe in network.pipes:
        mine = result.flows[pipe.id]
        ep = epanet_flows[pipe.id]
        ae = abs(abs(mine) - abs(ep))
        pe = ae / qmax * 100.0  # relative to the largest flow in the network
        pipe_rows.append({"pipe": pipe.id, "mine": mine, "epanet": ep,
                          "abs_err": ae, "pct_err": pe})
        if pe > max_flow_pe:
            max_flow_pe = pe
            max_flow_pipe = pipe.id

    return {
        "node_rows": node_rows,
        "pipe_rows": pipe_rows,
        "max_head_pct_err": max_head_pe,
        "max_head_node": max_head_node,
        "max_flow_pct_err": max_flow_pe,
        "max_flow_pipe": max_flow_pipe,
    }


def _network_payload(name: str, build, model: str = DW) -> Dict:
    net = build(model=model)
    result = _timed_solve(lambda: build(model=model), model=model)
    eh, ef = run_epanet(net, model=model)
    comparison = _compare(net, result, eh, ef)

    nodes = []
    for nid, node in net.nodes.items():
        nodes.append({
            "id": nid, "kind": node.kind, "elevation": node.elevation,
            "demand": node.demand,
            "head": result.heads[nid], "pressure_head": result.pressure_heads[nid],
        })
    pipes = []
    for pipe in net.pipes:
        pipes.append({
            "id": pipe.id, "start": pipe.start, "end": pipe.end,
            "length": pipe.length, "diameter": pipe.diameter,
            "roughness": pipe.roughness,
            "flow": result.flows[pipe.id], "velocity": result.velocities[pipe.id],
            "head_loss": result.head_losses[pipe.id],
        })

    return {
        "name": name,
        "n_nodes": len(net.nodes),
        "n_junctions": len(net.junctions),
        "n_reservoirs": len(net.reservoirs),
        "n_pipes": len(net.pipes),
        "model": result.model,
        "converged": result.converged,
        "iterations": result.iterations,
        "solve_time": result.solve_time,
        "max_residual": result.max_residual,
        "residual_history": result.residual_history,
        "tolerance": result.tolerance,
        "nodes": nodes,
        "pipes": pipes,
        "comparison": comparison,
    }


def _scalability(repeats: int = 5, model: str = DW) -> List[Dict]:
    """Solve a family of grids of increasing size and time each."""
    sizes = [(2, 2), (3, 3), (4, 4), (5, 5), (7, 7), (9, 9), (11, 11),
             (14, 14), (17, 17), (20, 20)]
    rows: List[Dict] = []
    for r, c in sizes:
        def build(r=r, c=c):
            return _grid_network(f"{r}x{c} grid", rows=r, cols=c,
                                 base_demand=0.004, model=model)
        best = _timed_solve(build, model=model, repeats=repeats)
        net = build()
        rows.append({
            "rows": r, "cols": c,
            "n_nodes": len(net.nodes), "n_pipes": len(net.pipes),
            "iterations": best.iterations, "solve_time": best.solve_time,
            "converged": best.converged,
        })
    return rows


def _tolerance_study(model: str = DW) -> List[Dict]:
    """Resolve Network 1 at a range of tolerances.

    The accuracy achieved against EPANET is a property of the method at a chosen
    stopping point, not of the formulation alone, so the headline error figure
    is reported alongside the tolerance that produced it.
    """
    net = loop_network(model=model)
    epanet_heads, _ = run_epanet(net, model=model)
    rows: List[Dict] = []
    for tol in (1e-4, 1e-6, 1e-8, 1e-10):
        result = solve_network(loop_network(model=model), model=model, tol=tol)
        dev = max(abs(result.heads[nid] - epanet_heads[nid])
                  for nid, node in net.nodes.items() if not node.is_reservoir)
        ref = max(abs(epanet_heads[nid])
                  for nid, node in net.nodes.items() if not node.is_reservoir)
        rows.append({
            "tolerance": tol,
            "iterations": result.iterations,
            "final_residual": result.max_residual,
            "max_head_dev": dev,
            "max_head_pct_dev": dev / ref * 100.0 if ref else 0.0,
            "converged": result.converged,
        })
    return rows


def compute_all(save: bool = True, model: str = DW) -> Dict:
    networks = [_network_payload(name, build, model=model)
                for name, build in NETWORK_BUILDERS]

    overall_head = max(n["comparison"]["max_head_pct_err"] for n in networks)
    overall_flow = max(n["comparison"]["max_flow_pct_err"] for n in networks)

    payload = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": model,
        "epsilon": EPSILON_CAST_IRON,
        "networks": networks,
        "scalability": _scalability(model=model),
        "tolerance_study": _tolerance_study(model=model),
        "overall_max_head_pct_err": overall_head,
        "overall_max_flow_pct_err": overall_flow,
        "overall_max_pct_err": max(overall_head, overall_flow),
    }

    if save:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        with open(os.path.join(RESULTS_DIR, "results.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    return payload


def load_results() -> Dict:
    path = os.path.join(RESULTS_DIR, "results.json")
    if not os.path.exists(path):
        return compute_all()
    with open(path, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    data = compute_all()
    print(f"Overall maximum error vs EPANET: {data['overall_max_pct_err']:.5f}%")
