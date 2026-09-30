"""Pipe network analysis by the nodal head correction method.

The single solver used by the analysis/validation scripts and by the Flask web
application. Import surface:

    from solver import solve_network, SolveResult, Network, Node, Pipe
    from solver import loop_network, medium_network, large_network
"""

from .core import SolveResult, solve_network
from .headloss import DW, HW
from .interpret import interpret
from .network import JUNCTION, RESERVOIR, Network, NetworkError, Node, Pipe
from .networks import (
    TEST_NETWORKS, loop_network, get_network, large_network, medium_network,
)
from .serialize import network_from_payload, network_to_payload

__all__ = [
    "solve_network", "SolveResult", "interpret",
    "Network", "Node", "Pipe", "NetworkError", "JUNCTION", "RESERVOIR",
    "HW", "DW",
    "loop_network", "medium_network", "large_network",
    "get_network", "TEST_NETWORKS",
    "network_from_payload", "network_to_payload",
]
