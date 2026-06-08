"""Shared plotting code for the project figures and the web application.

These functions are used both by figures/generate_figures.py and by the Flask
app, so the diagrams shown in the browser are produced
by exactly the same code as the static figures.
"""

from __future__ import annotations

import base64
import io
import math
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")  # headless backend, safe on a server
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import cm
from matplotlib.colors import Normalize

from solver.core import SolveResult
from solver.network import Network


def _auto_coords(network: Network) -> Dict[str, Tuple[float, float]]:
    """Return node coordinates, falling back to a circular layout if absent."""
    coords = {nid: n.coords for nid, n in network.nodes.items() if n.coords is not None}
    if len(coords) == len(network.nodes):
        return coords
    ids = list(network.nodes)
    n = len(ids)
    return {nid: (math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n))
            for i, nid in enumerate(ids)}


def plot_network(network: Network, result: SolveResult,
                 title: Optional[str] = None, figsize=(8.0, 6.0)):
    """Schematic diagram: nodes colour-coded by pressure head, flows on pipes.

    Pipe arrows point in the actual computed flow direction. For compact
    networks the flow magnitude is printed on each pipe; for large networks the
    labels are omitted to keep the diagram legible (direction and node colour
    still convey the result).
    """
    coords = _auto_coords(network)
    fig, ax = plt.subplots(figsize=figsize)

    junctions = [n for n in network.nodes.values() if not n.is_reservoir]
    pressures = [result.pressure_heads[n.id] for n in junctions]
    norm = Normalize(vmin=min(pressures), vmax=max(pressures)) if pressures else Normalize(0, 1)
    cmap = cm.get_cmap("viridis")

    label_pipes = len(network.pipes) <= 16

    # pipes
    for pipe in network.pipes:
        x0, y0 = coords[pipe.start]
        x1, y1 = coords[pipe.end]
        q = result.flows[pipe.id]
        # arrow points in the direction of positive flow (start->end if q>=0)
        if q >= 0:
            xs, ys, xe, ye = x0, y0, x1, y1
        else:
            xs, ys, xe, ye = x1, y1, x0, y0
        ax.plot([x0, x1], [y0, y1], color="0.55", lw=1.6, zorder=1)
        ax.annotate("", xy=(0.5 * (xs + xe), 0.5 * (ys + ye)),
                    xytext=(xs, ys),
                    arrowprops=dict(arrowstyle="-|>", color="#1f4e79", lw=1.4),
                    zorder=2)
        if label_pipes:
            mx, my = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
            ax.text(mx, my, f"{pipe.id}\n{abs(q)*1000:.1f} L/s",
                    fontsize=7.5, ha="center", va="center",
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="0.7", lw=0.5),
                    zorder=3)

    # reservoirs
    for r in network.reservoirs:
        x, y = coords[r.id]
        ax.scatter([x], [y], s=260, marker="s", c="#b0b0b0",
                   edgecolors="black", linewidths=1.0, zorder=4)
        ax.text(x, y, r.id, fontsize=8, ha="center", va="center", zorder=5)

    # junctions, coloured by pressure head
    jx = [coords[n.id][0] for n in junctions]
    jy = [coords[n.id][1] for n in junctions]
    # larger markers for small networks so node labels fit inside them
    marker_size = 320 if len(junctions) <= 12 else 90
    sc = ax.scatter(jx, jy, s=marker_size, c=pressures, cmap=cmap, norm=norm,
                    edgecolors="black", linewidths=0.8, zorder=4)
    # only label nodes when there are few enough for the text to sit cleanly
    if len(junctions) <= 12:
        for n in junctions:
            x, y = coords[n.id]
            ax.text(x, y, n.id, fontsize=7, ha="center", va="center",
                    color="white", zorder=5)

    cbar = fig.colorbar(sc, ax=ax, shrink=0.85)
    cbar.set_label("Pressure head (m)")
    ax.set_title(title or f"{network.name}: pressure heads and pipe flows")
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.set_aspect("equal", adjustable="datalim")
    ax.margins(0.12)
    fig.tight_layout()
    return fig


def plot_convergence(series: List[Tuple[str, List[float]]],
                     title: str = "Convergence of the nodal head correction method",
                     figsize=(7.5, 5.0)):
    """max|residual| (log y-axis) vs iteration for one or more networks."""
    fig, ax = plt.subplots(figsize=figsize)
    markers = ["o", "s", "^", "D", "v"]
    for i, (label, hist) in enumerate(series):
        iters = list(range(len(hist)))  # iteration 0 is the initial-guess residual
        ax.semilogy(iters, hist, marker=markers[i % len(markers)], lw=1.8,
                    markersize=5, label=label)
    ax.set_xlabel("Iteration")
    ax.set_ylabel("Maximum absolute continuity residual (m$^3$/s)")
    ax.set_title(title)
    ax.grid(True, which="both", ls=":", alpha=0.5)
    ax.legend()
    fig.tight_layout()
    return fig


def plot_validation_bars(network_name: str, node_rows: List[dict],
                         figsize=(9.0, 5.0), max_nodes: int = 18):
    """Paired bars: solver head vs EPANET head per node."""
    rows = node_rows if len(node_rows) <= max_nodes else node_rows[:max_nodes]
    labels = [r["node"] for r in rows]
    mine = [r["mine"] for r in rows]
    ep = [r["epanet"] for r in rows]
    x = np.arange(len(labels))
    w = 0.4

    fig, ax = plt.subplots(figsize=figsize)
    ax.bar(x - w / 2, mine, w, label="Nodal head solver", color="#1f77b4")
    ax.bar(x + w / 2, ep, w, label="EPANET (WNTR)", color="#ff7f0e")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Hydraulic head (m)")
    suffix = "" if len(node_rows) <= max_nodes else f" (first {max_nodes} nodes)"
    ax.set_title(f"Validation against EPANET: {network_name}{suffix}")
    lo = min(min(mine), min(ep))
    hi = max(max(mine), max(ep))
    pad = 0.05 * (hi - lo) if hi > lo else 1.0
    ax.set_ylim(lo - pad - 0.1 * (hi - lo + 1), hi + pad)
    ax.legend()
    ax.grid(True, axis="y", ls=":", alpha=0.5)
    fig.tight_layout()
    return fig


def plot_scalability(scal_rows: List[dict], figsize=(8.5, 5.0)):
    """Solve time and iteration count vs number of nodes."""
    nodes = [r["n_nodes"] for r in scal_rows]
    times_ms = [r["solve_time"] * 1000.0 for r in scal_rows]
    iters = [r["iterations"] for r in scal_rows]

    fig, ax1 = plt.subplots(figsize=figsize)
    color1 = "#1f77b4"
    ax1.plot(nodes, times_ms, marker="o", color=color1, lw=1.8, label="Solve time")
    ax1.set_xlabel("Number of nodes")
    ax1.set_ylabel("Solve time (ms)", color=color1)
    ax1.tick_params(axis="y", labelcolor=color1)
    ax1.grid(True, ls=":", alpha=0.5)

    ax2 = ax1.twinx()
    color2 = "#d62728"
    ax2.plot(nodes, iters, marker="s", color=color2, lw=1.8, ls="--",
             label="Iterations")
    ax2.set_ylabel("Iterations to convergence", color=color2)
    ax2.tick_params(axis="y", labelcolor=color2)
    ax2.set_ylim(0, max(iters) + 3)

    ax1.set_title("Computational performance and scalability")
    fig.tight_layout()
    return fig


def fig_to_base64_png(fig, dpi: int = 110) -> str:
    """Encode a matplotlib figure as a base64 PNG string (for the web app)."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")
