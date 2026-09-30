"""Independent hand-check of the Single-loop network by the Hardy Cross method.

This provides a verification route that is completely independent of the nodal
head correction solver: an initial continuity-satisfying flow distribution is
corrected loop by loop until the loop energy balance closes, exactly as in a
manual Hardy Cross calculation. The resulting pipe flows are then compared with
those from the Newton-Raphson nodal solver.

Run with:  python -m validation.hand_check
"""

from __future__ import annotations

from solver import DW, HW, loop_network, solve_network
from solver.headloss import (dw_resistance_from_flow, hw_resistance,
                             model_exponent)


def hardy_cross_loop(tol: float = 1e-9, max_iter: int = 100,
                        model: str = DW):
    """Solve the single loop J1-J2-J3 of the Single-loop network by Hardy Cross.

    Pipe flows are parameterised by the loop variable so continuity is satisfied
    exactly at every node throughout. The loop pipes are P2 (J1->J2),
    P4 (J2->J3) and P3 (J1->J3, traversed J3->J1 in the loop sense).

    Both head-loss models are supported. Under Hazen-Williams the resistance of
    each pipe is a constant; under Darcy-Weisbach it depends on the flow through
    the friction factor, so it is recomputed from the current loop flows at every
    correction, which is what a manual calculation would also do.
    """
    net = loop_network(model=model)
    pipes = {p.id: p for p in net.pipes}
    n = model_exponent(model)

    def resistance(pid, q):
        p = pipes[pid]
        if model == HW:
            return hw_resistance(p.length, p.diameter, p.roughness)
        return dw_resistance_from_flow(p.length, p.diameter, p.roughness, q)

    # initial continuity-satisfying guess (m3/s)
    x = 0.04                 # P2 = J1 -> J2
    history = []
    for it in range(1, max_iter + 1):
        Q_P2 = x
        Q_P3 = 0.05 - x      # J1 -> J3
        Q_P4 = x - 0.03      # J2 -> J3

        # loop traversal J1 -> J2 -> J3 -> J1: +P2, +P4, -P3
        loop = [("P2", Q_P2, +1), ("P4", Q_P4, +1), ("P3", Q_P3, -1)]
        num = 0.0   # sum of signed head losses
        den = 0.0   # sum of n*K*|Q|^(n-1)
        for pid, q, s in loop:
            qd = s * q       # flow in the loop direction
            kij = resistance(pid, qd)
            num += kij * abs(qd) ** (n - 1) * qd
            den += n * kij * abs(qd) ** (n - 1)
        dQ = -num / den
        x += dQ
        history.append(abs(dQ))
        if abs(dQ) < tol:
            break

    flows = {"P1": 0.10, "P2": x, "P3": 0.05 - x, "P4": x - 0.03}
    return flows, it, history


def main() -> int:
    hc_flows, iters, hist = hardy_cross_loop()
    net = loop_network(model=DW)
    nr = solve_network(net, model=DW)

    print("Independent Hardy Cross hand-check of the Single-loop network")
    print(f"  Hardy Cross converged in {iters} loop corrections "
          f"(final |dQ| = {hist[-1]:.2e} m3/s)")
    print(f"  {'pipe':<6}{'Hardy Cross':>16}{'Newton solver':>16}{'abs diff':>14}")
    max_diff = 0.0
    for pid in ["P1", "P2", "P3", "P4"]:
        hc = hc_flows[pid]
        nrq = nr.flows[pid]
        diff = abs(hc - nrq)
        max_diff = max(max_diff, diff)
        print(f"  {pid:<6}{hc*1000:>14.5f} L/s{nrq*1000:>14.5f} L/s{diff*1000:>12.6f} L/s")
    print(f"  maximum difference between the two independent methods: "
          f"{max_diff*1000:.6f} L/s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
