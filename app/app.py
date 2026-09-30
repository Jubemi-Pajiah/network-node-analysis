"""Interactive web application for the nodal head correction solver.

This app imports the SAME solver used to produce the validation results
(there is exactly one solver in the codebase) and the SAME plotting code used
for the static figures. It serves an editable network, re-solves on demand,
and returns results together with base64-encoded PNG diagrams.

WSGI entry point: app.app:app  (e.g. gunicorn app.app:app)
"""

from __future__ import annotations

import os
import sys

# allow "import solver" / "import plotting" when run from the app directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from flask import Flask, jsonify, render_template, request  # noqa: E402

from plotting import fig_to_base64_png, plot_convergence, plot_network  # noqa: E402
from solver import (DW, HW, NetworkError, loop_network, get_network,  # noqa: E402
                    interpret, network_from_payload, network_to_payload,
                    solve_network)

app = Flask(__name__)

# preset key -> human label, mirrored in the front-end selector
PRESETS = {
    "loop": "Single-loop network (4 nodes)",
    "medium": "Medium grid network (26 nodes)",
    "large": "Large grid network (122 nodes)",
}


@app.route("/")
def index():
    """Serve the page pre-populated with the Single-loop network."""
    preset = network_to_payload(loop_network())
    return render_template("index.html", preset=preset, presets=PRESETS)


@app.route("/preset/<key>")
def preset(key: str):
    """Return one of the three test networks as JSON for the editor.

    The roughness column means different things under the two head-loss models
    (Hazen-Williams C, or absolute roughness in metres), so the preset is built
    for whichever model the caller is about to solve with.
    """
    model = request.args.get("model", DW)
    if model not in (HW, DW):
        return jsonify({"ok": False, "error": f"unknown head-loss model '{model}'"}), 400
    try:
        net = get_network(key, model=model)
    except KeyError:
        return jsonify({"ok": False, "error": f"unknown preset '{key}'"}), 404
    return jsonify({"ok": True, "network": network_to_payload(net)})


@app.route("/solve", methods=["POST"])
def solve():
    """Run the imported solver on the posted network and return results."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"ok": False, "error": "request body must be valid JSON"}), 400

    # parse optional solver controls
    model = data.get("model", DW)
    if model not in (HW, DW):
        return jsonify({"ok": False, "error": f"unknown head-loss model '{model}'"}), 400
    try:
        tol = float(data.get("tol", 1e-6))
        max_iter = int(data.get("max_iter", 100))
        if tol <= 0 or max_iter < 1:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"ok": False,
                        "error": "tolerance must be > 0 and max iterations >= 1"}), 400

    # build and solve, converting any problem into a readable message
    try:
        net = network_from_payload(data)
        result = solve_network(net, model=model, tol=tol, max_iter=max_iter)
    except NetworkError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:  # never leak a 500 stack trace to the client
        return jsonify({"ok": False, "error": f"solver error: {exc}"}), 400

    if not result.converged:
        # still return what we have, flagged, so the UI can warn the user
        warning = (f"solver did not converge within {max_iter} iterations "
                   f"(max residual {result.max_residual:.2e} m3/s)")
    else:
        warning = None

    # diagrams, produced by the SAME plotting code as the static figures
    try:
        diagram = fig_to_base64_png(plot_network(net, result))
        convergence = fig_to_base64_png(
            plot_convergence([(net.name, result.residual_history)],
                             title="Convergence (max residual vs iteration)"))
    except Exception as exc:
        diagram = convergence = None
        warning = (warning + "; " if warning else "") + f"figure error: {exc}"

    nodes = []
    for nid, node in net.nodes.items():
        nodes.append({
            "id": nid, "type": node.kind,
            "elevation": node.elevation, "demand": node.demand,
            "head": result.heads[nid], "pressure_head": result.pressure_heads[nid],
        })
    pipes = []
    for pipe in net.pipes:
        pipes.append({
            "id": pipe.id, "from": pipe.start, "to": pipe.end,
            "flow": result.flows[pipe.id], "velocity": result.velocities[pipe.id],
            "head_loss": result.head_losses[pipe.id],
        })

    # plain-language interpretation of the result (rule-based, from solver output)
    try:
        interpretation = interpret(net, result)
    except Exception:
        interpretation = []

    return jsonify({
        "ok": True,
        "warning": warning,
        "interpretation": interpretation,
        "model": result.model,
        "converged": result.converged,
        "iterations": result.iterations,
        "max_residual": result.max_residual,
        "solve_time_ms": result.solve_time * 1000.0,
        "nodes": nodes,
        "pipes": pipes,
        "diagram_png": diagram,
        "convergence_png": convergence,
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
