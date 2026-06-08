"""Validation script: compares the nodal head correction solver against EPANET.

Run with:  python -m validation.validate

For every network it prints a node-head comparison table and a pipe-flow
comparison table (solver value, EPANET value, absolute error, percent error),
then prints the maximum percent error across all networks. Acceptance target is
a maximum error below 0.1 percent.
"""

from __future__ import annotations

import sys

from analysis import compute_all


def _print_network(net: dict) -> None:
    print("=" * 78)
    print(f"NETWORK: {net['name']}  ({net['n_nodes']} nodes, {net['n_pipes']} pipes)")
    print(f"  solver: {net['model']}, converged={net['converged']}, "
          f"iterations={net['iterations']}, max|residual|={net['max_residual']:.3e} m3/s")
    print("-" * 78)
    print("Node head comparison (m)")
    print(f"  {'node':<8}{'solver':>14}{'EPANET':>14}{'abs err':>14}{'% err':>12}")
    for row in net["comparison"]["node_rows"]:
        print(f"  {row['node']:<8}{row['mine']:>14.5f}{row['epanet']:>14.5f}"
              f"{row['abs_err']:>14.2e}{row['pct_err']:>12.5f}")
    print("-" * 78)
    print("Pipe flow comparison (m3/s)  [% err relative to largest network flow]")
    print(f"  {'pipe':<8}{'solver':>14}{'EPANET':>14}{'abs err':>14}{'% err':>12}")
    rows = net["comparison"]["pipe_rows"]
    shown = rows if len(rows) <= 12 else rows[:12]
    for row in shown:
        print(f"  {row['pipe']:<8}{row['mine']:>14.6f}{row['epanet']:>14.6f}"
              f"{row['abs_err']:>14.2e}{row['pct_err']:>12.5f}")
    if len(rows) > 12:
        print(f"  ... ({len(rows) - 12} more pipes)")
    c = net["comparison"]
    print("-" * 78)
    print(f"  max head error: {c['max_head_pct_err']:.5f}% (node {c['max_head_node']});  "
          f"max flow error: {c['max_flow_pct_err']:.5f}% (pipe {c['max_flow_pipe']})")
    print()


def main() -> int:
    data = compute_all()
    for net in data["networks"]:
        _print_network(net)

    overall = data["overall_max_pct_err"]
    print("=" * 78)
    print(f"OVERALL MAXIMUM ERROR vs EPANET: {overall:.5f} %")
    print(f"  (max head error {data['overall_max_head_pct_err']:.5f} %, "
          f"max flow error {data['overall_max_flow_pct_err']:.5f} %)")
    target = 0.1
    if overall < target:
        print(f"  PASS: maximum error {overall:.5f}% is below the {target}% acceptance target.")
        return 0
    print(f"  FAIL: maximum error {overall:.5f}% exceeds the {target}% acceptance target.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
