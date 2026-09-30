"""Network data structures for the nodal head correction solver.

This module defines the node and pipe data structures used throughout the
project. The same structures feed the solver, the validation scripts and the
Flask web application, so there is exactly one network representation in the
codebase.

Notation:

    z_j      node elevation (m)
    q_j      external demand at a node (m3/s), positive for withdrawal
    H_j      hydraulic (piezometric) head at a node (m), the primary unknown
    p_j/gamma  pressure head = H_j - z_j (m)
    L_ij     pipe length (m)
    D_ij     pipe internal diameter (m)
    Q_ij     pipe flow (m3/s), positive when flowing from node i to node j
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


RESERVOIR = "reservoir"
JUNCTION = "junction"


@dataclass
class Node:
    """A single network node.

    A reservoir is a fixed-head boundary node (its head never changes during the
    solution). A junction is an interior node whose head is an unknown to be
    determined.
    """

    id: str
    kind: str = JUNCTION          # "reservoir" or "junction"
    elevation: float = 0.0        # z_j, m above datum
    demand: float = 0.0           # q_j, m3/s, positive = withdrawal
    fixed_head: Optional[float] = None  # H_r for reservoirs, m
    coords: Optional[Tuple[float, float]] = None  # (x, y) for plotting

    def __post_init__(self) -> None:
        if self.kind not in (RESERVOIR, JUNCTION):
            raise ValueError(f"node {self.id}: kind must be '{RESERVOIR}' or '{JUNCTION}'")
        if self.kind == RESERVOIR and self.fixed_head is None:
            raise ValueError(f"reservoir {self.id} requires a fixed_head value")

    @property
    def is_reservoir(self) -> bool:
        return self.kind == RESERVOIR


@dataclass
class Pipe:
    """A single pipe (link) connecting two nodes.

    roughness carries the Hazen-Williams coefficient C (dimensionless) when the
    Hazen-Williams model is used, or the absolute roughness epsilon (m) when the
    Darcy-Weisbach model is used.
    """

    id: str
    start: str        # "from" node id
    end: str          # "to" node id
    length: float     # L_ij, m
    diameter: float   # D_ij, m
    roughness: float  # C (Hazen-Williams) or epsilon in m (Darcy-Weisbach)


@dataclass
class Network:
    """A pipe network: a collection of nodes and pipes.

    The network is a directed graph where pipe direction only defines the
    positive sign convention for flow; the actual flow direction is solved, not
    assumed.
    """

    name: str = "network"
    nodes: Dict[str, Node] = field(default_factory=dict)
    pipes: List[Pipe] = field(default_factory=list)

    # ------------------------------------------------------------------ builders
    def add_node(self, node: Node) -> Node:
        if node.id in self.nodes:
            raise ValueError(f"duplicate node id: {node.id}")
        self.nodes[node.id] = node
        return node

    def add_junction(self, id: str, elevation: float = 0.0, demand: float = 0.0,
                     coords: Optional[Tuple[float, float]] = None) -> Node:
        return self.add_node(Node(id=id, kind=JUNCTION, elevation=elevation,
                                  demand=demand, coords=coords))

    def add_reservoir(self, id: str, fixed_head: float,
                      coords: Optional[Tuple[float, float]] = None) -> Node:
        return self.add_node(Node(id=id, kind=RESERVOIR, elevation=fixed_head,
                                  fixed_head=fixed_head, coords=coords))

    def add_pipe(self, id: str, start: str, end: str, length: float,
                 diameter: float, roughness: float) -> Pipe:
        pipe = Pipe(id=id, start=start, end=end, length=length,
                    diameter=diameter, roughness=roughness)
        self.pipes.append(pipe)
        return pipe

    # ------------------------------------------------------------------ queries
    @property
    def junctions(self) -> List[Node]:
        return [n for n in self.nodes.values() if n.kind == JUNCTION]

    @property
    def reservoirs(self) -> List[Node]:
        return [n for n in self.nodes.values() if n.kind == RESERVOIR]

    def neighbours(self) -> Dict[str, List[Tuple[str, Pipe, int]]]:
        """For each node id, list of (other-node-id, pipe, orientation).

        orientation is +1 if the node is the pipe's "end" (flow Q is into the
        node when positive) and -1 if it is the pipe's "start".
        """
        adj: Dict[str, List[Tuple[str, Pipe, int]]] = {nid: [] for nid in self.nodes}
        for pipe in self.pipes:
            adj[pipe.start].append((pipe.end, pipe, -1))
            adj[pipe.end].append((pipe.start, pipe, +1))
        return adj

    # ------------------------------------------------------------------ validation
    def validate(self) -> None:
        """Raise NetworkError describing any structural problem.

        Checks: at least one reservoir, all pipe endpoints exist, positive
        geometry, and full connectivity to a reservoir.
        """
        if not self.reservoirs:
            raise NetworkError("network has no reservoir (fixed-head boundary node)")

        for pipe in self.pipes:
            for end in (pipe.start, pipe.end):
                if end not in self.nodes:
                    raise NetworkError(f"pipe {pipe.id} references unknown node '{end}'")
            if pipe.start == pipe.end:
                raise NetworkError(f"pipe {pipe.id} connects node '{pipe.start}' to itself")
            if pipe.length <= 0:
                raise NetworkError(f"pipe {pipe.id} has non-positive length {pipe.length}")
            if pipe.diameter <= 0:
                raise NetworkError(f"pipe {pipe.id} has non-positive diameter {pipe.diameter}")
            if pipe.roughness <= 0:
                raise NetworkError(f"pipe {pipe.id} has non-positive roughness {pipe.roughness}")

        # connectivity: every node must reach a reservoir through pipes
        adj = self.neighbours()
        reservoir_ids = {r.id for r in self.reservoirs}
        seen = set(reservoir_ids)
        stack = list(reservoir_ids)
        while stack:
            cur = stack.pop()
            for other, _pipe, _o in adj[cur]:
                if other not in seen:
                    seen.add(other)
                    stack.append(other)
        disconnected = set(self.nodes) - seen
        if disconnected:
            raise NetworkError(
                "these nodes are not connected to any reservoir: "
                + ", ".join(sorted(disconnected))
            )


class NetworkError(ValueError):
    """Raised for malformed or hydraulically invalid networks."""
