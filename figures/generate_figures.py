"""Generate the static figures from real solver output.

Run with:  python -m figures.generate_figures

Produces, in the figures/ directory:
  * one schematic diagram per network (nodes colour-coded by pressure head,
    pipes labelled with flow magnitude and direction),
  * a combined convergence plot overlaying all three networks,
  * a validation comparison bar chart per network (solver vs EPANET heads),
  * a scalability plot (solve time and iterations vs network size).
"""

from __future__ import annotations

import os

from analysis import compute_all
from plotting import (plot_convergence, plot_network, plot_scalability,
                      plot_validation_bars)
from solver import loop_network, large_network, medium_network, solve_network

FIG_DIR = os.path.dirname(__file__)

# fixed mapping from network key to builder and figure file stem
NETWORKS = [
    ("Single-loop network", loop_network, "network1"),
    ("Medium grid network", medium_network, "network2"),
    ("Large grid network", large_network, "network3"),
]


def _save(fig, name: str) -> str:
    path = os.path.join(FIG_DIR, name)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    import matplotlib.pyplot as plt
    plt.close(fig)
    print(f"  wrote {name}")
    return path


def main() -> int:
    data = compute_all()
    by_name = {n["name"]: n for n in data["networks"]}

    print("Generating figures from solver output...")

    # Figure type 1: schematic diagram per network
    series = []
    for name, build, stem in NETWORKS:
        net = build()
        res = solve_network(net)
        fig = plot_network(net, res, title=f"{name}: pressure heads and pipe flows")
        _save(fig, f"fig_{stem}_schematic.png")
        series.append((name, res.residual_history))

    # Figure type 2: convergence plot overlaying all three networks
    fig = plot_convergence(series)
    _save(fig, "fig_convergence.png")

    # Figure type 3: validation bar chart per network
    for name, build, stem in NETWORKS:
        rows = by_name[name]["comparison"]["node_rows"]
        fig = plot_validation_bars(name, rows)
        _save(fig, f"fig_{stem}_validation.png")

    # Figure type 4: scalability plot
    fig = plot_scalability(data["scalability"])
    _save(fig, "fig_scalability.png")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
