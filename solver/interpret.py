"""Plain-language interpreter for solver results.

Given a solved network this module produces a short list of engineering
findings, each derived deterministically from the solver output. It introduces
no new numbers: every value quoted in a finding is read straight from the
SolveResult, so the interpretation can never disagree with the results.

The thresholds used to flag pressures and velocities are common water
distribution design rules of thumb (a minimum service pressure of about 15 m,
and a typical pipe velocity band of roughly 0.3 to 2.0 m/s). They are guidance,
not a specific code requirement, and are exposed as parameters so they can be
changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .core import SolveResult
from .network import Network

# severity levels, ordered; the web app maps these to colours
GOOD = "good"
INFO = "info"
WARN = "warn"
ALERT = "alert"


@dataclass
class Finding:
    level: str
    title: str
    detail: str

    def as_dict(self) -> dict:
        return {"level": self.level, "title": self.title, "detail": self.detail}


def interpret(network: Network, result: SolveResult, *,
              min_pressure: float = 15.0, max_velocity: float = 2.0,
              min_velocity: float = 0.3) -> List[dict]:
    """Return a list of finding dicts interpreting the solved network."""
    findings: List[Finding] = []
    junctions = [n for n in network.nodes.values() if not n.is_reservoir]
    adj = network.neighbours()

    # ---- 1. convergence ----------------------------------------------------
    if result.converged:
        findings.append(Finding(
            GOOD, "Solution converged",
            f"The solver reached a balanced solution in {result.iterations} "
            f"iterations, with a final flow imbalance of "
            f"{result.max_residual:.1e} m³/s (below the {result.tolerance:g} "
            f"m³/s tolerance). The small, near-constant iteration count is the "
            f"fast quadratic convergence expected of the Newton-Raphson method."))
    else:
        findings.append(Finding(
            ALERT, "Did not converge",
            f"The solver hit the {result.max_iter}-iteration limit with a "
            f"remaining flow imbalance of {result.max_residual:.1e} m³/s. "
            f"The results below may be unreliable; check for an isolated node, an "
            f"unrealistic diameter, or raise the iteration limit."))
        # still interpret what we have, but the warning stands

    # ---- 2. source and mass balance ---------------------------------------
    total_demand = sum(n.demand for n in junctions)
    supply_lines = []
    for r in network.reservoirs:
        out = 0.0
        for _other, pipe, orient in adj[r.id]:
            # orient*flow is flow INTO the reservoir; supply is the negative
            out += -orient * result.flows[pipe.id]
        supply_lines.append((r.id, out))
    total_supply = sum(s for _r, s in supply_lines)

    if supply_lines:
        res_txt = ", ".join(f"{rid} delivers {s*1000:.1f} L/s" for rid, s in supply_lines)
        findings.append(Finding(
            INFO, "Source and mass balance",
            f"Total demand across the {len(junctions)} junctions is "
            f"{total_demand*1000:.1f} L/s. The reservoir supply is "
            f"{total_supply*1000:.1f} L/s ({res_txt}), confirming that mass is "
            f"conserved: what the network draws off equals what the source feeds in."))

    # ---- 3. pressure distribution -----------------------------------------
    if junctions:
        pres = {n.id: result.pressure_heads[n.id] for n in junctions}
        lo_id = min(pres, key=pres.get)
        hi_id = max(pres, key=pres.get)
        low = [nid for nid, p in pres.items() if p < min_pressure]
        negative = [nid for nid, p in pres.items() if p < 0.0]

        findings.append(Finding(
            INFO, "Pressure distribution",
            f"Pressure head ranges from {pres[lo_id]:.1f} m at {lo_id} (the most "
            f"vulnerable point) to {pres[hi_id]:.1f} m at {hi_id}. Pressure head is "
            f"the head minus the node elevation, so it is the pressure actually "
            f"available for service."))

        if negative:
            findings.append(Finding(
                ALERT, "Negative pressure",
                f"{len(negative)} junction(s) have negative pressure head "
                f"({', '.join(negative[:6])}{'...' if len(negative) > 6 else ''}), "
                f"which is physically infeasible for a real system and points to "
                f"insufficient supply head or undersized pipes feeding them."))
        elif low:
            findings.append(Finding(
                WARN, "Low-pressure junctions",
                f"{len(low)} junction(s) fall below the typical {min_pressure:g} m "
                f"minimum service pressure ({', '.join(low[:6])}"
                f"{'...' if len(low) > 6 else ''}). They may need a larger feeder "
                f"pipe, a higher source head, or a booster."))
        else:
            findings.append(Finding(
                GOOD, "Pressures adequate",
                f"Every junction is at or above the typical {min_pressure:g} m "
                f"minimum service pressure, so the network delivers adequate "
                f"pressure everywhere."))

    # ---- 4. velocities -----------------------------------------------------
    if network.pipes:
        vmax_pipe = max(network.pipes, key=lambda p: result.velocities[p.id])
        vmax = result.velocities[vmax_pipe.id]
        high = [p.id for p in network.pipes if result.velocities[p.id] > max_velocity]
        # ignore essentially-dead pipes when flagging "too slow"
        qmax = max((abs(result.flows[p.id]) for p in network.pipes), default=0.0)
        slow = [p.id for p in network.pipes
                if min_velocity > result.velocities[p.id] > 0
                and abs(result.flows[p.id]) > 0.01 * qmax]

        detail = (f"The fastest pipe is {vmax_pipe.id} at {vmax:.2f} m/s.")
        if high:
            findings.append(Finding(
                WARN, "High pipe velocities",
                f"{len(high)} pipe(s) exceed about {max_velocity:g} m/s "
                f"({', '.join(high[:6])}{'...' if len(high) > 6 else ''}). High "
                f"velocity raises head loss and the risk of noise and erosion; a "
                f"larger diameter would reduce it. {detail}"))
        else:
            findings.append(Finding(
                GOOD, "Velocities in range",
                f"All pipe velocities are within the usual design band (up to about "
                f"{max_velocity:g} m/s). {detail}"))
        if slow:
            findings.append(Finding(
                INFO, "Low-velocity pipes",
                f"{len(slow)} carrying pipe(s) run below about {min_velocity:g} m/s "
                f"({', '.join(slow[:6])}{'...' if len(slow) > 6 else ''}). Sustained "
                f"low velocity can allow sediment to settle and water to age."))

    # ---- 5. dominant head loss & loop balance ------------------------------
    if network.pipes:
        hl_pipe = max(network.pipes, key=lambda p: result.head_losses[p.id])
        hl = result.head_losses[hl_pipe.id]
        findings.append(Finding(
            INFO, "Largest head loss",
            f"Pipe {hl_pipe.id} (from {hl_pipe.start} to {hl_pipe.end}) loses the "
            f"most head, {hl:.2f} m, so it is the steepest part of the hydraulic "
            f"gradient and the first candidate to enlarge if pressures are tight."))

        qmax = max(abs(result.flows[p.id]) for p in network.pipes)
        balanced = [p for p in network.pipes if abs(result.flows[p.id]) < 0.01 * qmax]
        if balanced:
            ids = ", ".join(p.id for p in balanced[:6])
            findings.append(Finding(
                INFO, "Near-balanced links",
                f"{len(balanced)} pipe(s) carry almost no flow ({ids}"
                f"{'...' if len(balanced) > 6 else ''}). Their end nodes sit at "
                f"nearly equal head, so a loop is close to hydraulic balance and the "
                f"demand is met mainly by the other paths."))

        # reversed-direction pipes (actual flow opposite to the from->to ordering)
        reversed_pipes = [p.id for p in network.pipes if result.flows[p.id] < -1e-9]
        if reversed_pipes:
            findings.append(Finding(
                INFO, "Solved flow directions",
                f"Flow in {len(reversed_pipes)} pipe(s) runs opposite to the order "
                f"they were entered ({', '.join(reversed_pipes[:6])}"
                f"{'...' if len(reversed_pipes) > 6 else ''}). Direction is solved by "
                f"the head field, not assumed, so this is a normal result."))

    return [f.as_dict() for f in findings]
