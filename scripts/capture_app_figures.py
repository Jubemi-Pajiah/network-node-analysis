"""Capture the two web-application output figures shown in the README.

These are the diagram and convergence plot returned by the running Flask
application for the Single-loop network, as evidence that the deployed tool runs
the same validated solver. Those images are produced by POSTing the network to
the real /solve endpoint through Flask's test client, so they are genuine
application output rather than a re-plot.

Run:  python -m scripts.capture_app_figures
"""

from __future__ import annotations

import base64
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.app import app  # noqa: E402
from solver import DW, loop_network, network_to_payload  # noqa: E402

FIGURES = os.path.join(ROOT, "figures")

TARGETS = {
    "diagram_png": "app_output_diagram.png",
    "convergence_png": "app_output_convergence.png",
}


def main():
    payload = network_to_payload(loop_network(model=DW))
    payload.update({"model": DW, "tol": 1e-6, "max_iter": 100})

    client = app.test_client()
    response = client.post("/solve", json=payload)
    if response.status_code != 200:
        raise SystemExit(f"/solve returned {response.status_code}: {response.data[:300]}")

    data = response.get_json()
    if not data.get("ok"):
        raise SystemExit(f"/solve reported an error: {data.get('error')}")

    print(f"/solve ok: model={data['model']} iterations={data['iterations']}")

    os.makedirs(FIGURES, exist_ok=True)
    for key, filename in TARGETS.items():
        encoded = data.get(key)
        if not encoded:
            raise SystemExit(f"response carried no {key}")
        if "," in encoded:  # strip a data: URI prefix if present
            encoded = encoded.split(",", 1)[1]
        path = os.path.join(FIGURES, filename)
        with open(path, "wb") as handle:
            handle.write(base64.b64decode(encoded))
        print(f"  wrote {filename} ({os.path.getsize(path)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
