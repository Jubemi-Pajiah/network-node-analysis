"""Bridge that reproduces a solver Network inside EPANET via the WNTR package.

The same network definition is fed to EPANET so the comparison is a
like-for-like check of the nodal head correction solver against the reference
EPANET hydraulic engine (Rossman, 2000), accessed through WNTR (Klise et al.,
2017).
"""

from __future__ import annotations

import os
import warnings
from typing import Dict, Tuple

import wntr

from solver.headloss import DW
from solver.network import Network

warnings.filterwarnings("ignore")

# EPANET writes .inp/.bin/.rpt scratch files next to this prefix; keep them out
# of the repository root.
_SCRATCH_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scratch")
_TEMP_PREFIX = os.path.join(_SCRATCH_DIR, "temp")


def build_wntr_model(network: Network,
                     model: str = DW) -> "wntr.network.WaterNetworkModel":
    """Construct an equivalent WNTR/EPANET model under the given head-loss model.

    Minor losses are set to zero (consistent with the solver scope) and the
    demand model is demand-driven, matching the solver assumptions. Pipe
    roughness is passed through unchanged: WNTR works in SI throughout, so the
    Hazen-Williams coefficient C and the Darcy-Weisbach absolute roughness in
    metres are both accepted in the same units the solver uses.
    """
    wn = wntr.network.WaterNetworkModel()
    wn.options.hydraulic.headloss = model
    wn.options.hydraulic.demand_model = "DD"
    wn.options.time.duration = 0  # single steady-state snapshot

    for node in network.nodes.values():
        if node.is_reservoir:
            wn.add_reservoir(node.id, base_head=float(node.fixed_head))
        else:
            wn.add_junction(node.id, base_demand=float(node.demand),
                            elevation=float(node.elevation))

    for pipe in network.pipes:
        wn.add_pipe(pipe.id, pipe.start, pipe.end, length=float(pipe.length),
                    diameter=float(pipe.diameter), roughness=float(pipe.roughness),
                    minor_loss=0.0, check_valve=False)
    return wn


def run_epanet(network: Network,
               model: str = DW) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Return (heads, flows) from EPANET for the given network.

    heads maps node id -> head (m); flows maps pipe id -> flow (m3/s, positive
    in the start-to-end direction, matching the solver convention).
    """
    wn = build_wntr_model(network, model=model)
    sim = wntr.sim.EpanetSimulator(wn)
    os.makedirs(_SCRATCH_DIR, exist_ok=True)
    results = sim.run_sim(file_prefix=_TEMP_PREFIX)

    heads = {nid: float(results.node["head"][nid].iloc[0]) for nid in wn.node_name_list}
    flows = {pid: float(results.link["flowrate"][pid].iloc[0]) for pid in wn.link_name_list}
    return heads, flows
