"""The three test networks used for validation and benchmarking.

Network 1: a small single-loop network (4 nodes, one loop), small enough to
           check by hand with the Hardy Cross method.
Network 2: a medium multi-loop grid network (26 nodes, 40 pipes), a standard
           form of looped test network used for studying solver behaviour on
           highly meshed systems in the 20 to 50 node range.
Network 3: a large multi-loop grid network (122 nodes, 220 pipes) used to study
           computational performance and scalability beyond 100 nodes.

All three are built in this single module so the solver, the validation script,
the figure generator and the web application all use identical definitions.
"""

from __future__ import annotations

from .network import Network


def loop_network() -> Network:
    """Network 1: the small single-loop network.

    Reservoir head 100 m; junctions J1 (z=50, q=0.05), J2 (z=45, q=0.03),
    J3 (z=40, q=0.02). Pipes P1 Res-J1, P2 J1-J2, P3 J1-J3, P4 J2-J3.
    Uniform Hazen-Williams C = 130.
    """
    net = Network(name="Single-loop network")
    net.add_reservoir("Res", fixed_head=100.0, coords=(0.0, 2.0))
    net.add_junction("J1", elevation=50.0, demand=0.05, coords=(1.0, 2.0))
    net.add_junction("J2", elevation=45.0, demand=0.03, coords=(2.0, 2.7))
    net.add_junction("J3", elevation=40.0, demand=0.02, coords=(2.0, 1.3))

    C = 130.0
    net.add_pipe("P1", "Res", "J1", length=1000.0, diameter=0.30, roughness=C)
    net.add_pipe("P2", "J1", "J2", length=800.0, diameter=0.25, roughness=C)
    net.add_pipe("P3", "J1", "J3", length=600.0, diameter=0.20, roughness=C)
    net.add_pipe("P4", "J2", "J3", length=700.0, diameter=0.22, roughness=C)
    return net


def _grid_network(name: str, rows: int, cols: int, *, C: float = 120.0,
                  reservoir_head: float = 100.0, base_demand: float = 0.012,
                  spacing: float = 500.0, diameter: float = 0.30,
                  base_elev: float = 30.0) -> Network:
    """Build a rows x cols looped grid network.

    Junctions sit on a regular grid and are joined to their right and lower
    neighbours, producing a fully meshed network with (rows-1)*(cols-1) loops.
    A single reservoir is attached at the top-left corner. Node elevations vary
    smoothly across the grid so the pressure field is non-trivial.
    """
    net = Network(name=name)

    def jid(r: int, c: int) -> str:
        return f"J{r}_{c}"

    # reservoir just to the left of the top-left junction
    net.add_reservoir("Res", fixed_head=reservoir_head, coords=(-1.0, 0.0))

    for r in range(rows):
        for c in range(cols):
            elev = base_elev + 1.5 * r + 1.0 * c
            net.add_junction(jid(r, c), elevation=elev, demand=base_demand,
                             coords=(float(c), float(-r)))

    # feeder pipe from reservoir to the corner junction
    pno = 0
    net.add_pipe("P0", "Res", jid(0, 0), length=spacing, diameter=0.45, roughness=C)

    for r in range(rows):
        for c in range(cols):
            if c + 1 < cols:  # horizontal pipe
                pno += 1
                net.add_pipe(f"H{r}_{c}", jid(r, c), jid(r, c + 1),
                             length=spacing, diameter=diameter, roughness=C)
            if r + 1 < rows:  # vertical pipe
                pno += 1
                net.add_pipe(f"V{r}_{c}", jid(r, c), jid(r + 1, c),
                             length=spacing, diameter=diameter, roughness=C)
    return net


def medium_network() -> Network:
    """Network 2: a 5 x 5 looped grid (26 nodes, 40 pipes, 16 loops)."""
    return _grid_network("Medium grid network", rows=5, cols=5,
                         C=120.0, base_demand=0.012, diameter=0.30)


def large_network() -> Network:
    """Network 3: an 11 x 11 looped grid (122 nodes, 220 pipes, 100 loops)."""
    return _grid_network("Large grid network", rows=11, cols=11,
                         C=120.0, base_demand=0.004, diameter=0.30,
                         reservoir_head=120.0)


# Registry used by the web-app preset selector and the validation script.
TEST_NETWORKS = {
    "loop": ("Single-loop network", loop_network),
    "medium": ("Medium grid network", medium_network),
    "large": ("Large grid network", large_network),
}


def get_network(key: str) -> Network:
    if key not in TEST_NETWORKS:
        raise KeyError(f"unknown network preset '{key}'")
    return TEST_NETWORKS[key][1]()
