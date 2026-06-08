"""Serialisation between the JSON used by the web app and Network objects.

Kept inside the solver package so the web application constructs networks
through the same canonical code path used everywhere else.
"""

from __future__ import annotations

from typing import Dict

from .network import JUNCTION, RESERVOIR, Network, NetworkError, Node, Pipe


def network_to_payload(net: Network) -> Dict:
    """Export a Network to the JSON-friendly dict consumed by the front end."""
    nodes = []
    for n in net.nodes.values():
        nodes.append({
            "id": n.id,
            "type": n.kind,
            "elevation": n.elevation,
            "demand": n.demand,
            "fixed_head": n.fixed_head if n.fixed_head is not None else "",
            "coords": list(n.coords) if n.coords else None,
        })
    pipes = []
    for p in net.pipes:
        pipes.append({
            "id": p.id, "from": p.start, "to": p.end,
            "length": p.length, "diameter": p.diameter, "roughness": p.roughness,
        })
    return {"name": net.name, "nodes": nodes, "pipes": pipes}


def _num(value, field: str, node_or_pipe: str, allow_blank=False):
    if value is None or value == "":
        if allow_blank:
            return None
        raise NetworkError(f"{node_or_pipe}: '{field}' must be a number, got blank")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise NetworkError(f"{node_or_pipe}: '{field}' must be a number, got '{value}'")


def network_from_payload(data: Dict) -> Network:
    """Build a Network from posted JSON, raising NetworkError on malformed data."""
    if not isinstance(data, dict):
        raise NetworkError("request body must be a JSON object")
    nodes = data.get("nodes")
    pipes = data.get("pipes")
    if not isinstance(nodes, list) or not nodes:
        raise NetworkError("at least one node is required")
    if not isinstance(pipes, list) or not pipes:
        raise NetworkError("at least one pipe is required")

    net = Network(name=data.get("name", "user network"))
    seen_ids = set()
    for raw in nodes:
        nid = str(raw.get("id", "")).strip()
        if not nid:
            raise NetworkError("every node needs a non-empty id")
        if nid in seen_ids:
            raise NetworkError(f"duplicate node id '{nid}'")
        seen_ids.add(nid)
        kind = str(raw.get("type", JUNCTION)).strip().lower()
        coords = raw.get("coords")
        coords = tuple(coords) if coords else None
        if kind == RESERVOIR:
            fh = _num(raw.get("fixed_head"), "fixed_head", f"reservoir {nid}")
            net.add_reservoir(nid, fixed_head=fh, coords=coords)
        elif kind == JUNCTION:
            net.add_junction(
                nid,
                elevation=_num(raw.get("elevation", 0.0), "elevation", f"junction {nid}"),
                demand=_num(raw.get("demand", 0.0), "demand", f"junction {nid}"),
                coords=coords,
            )
        else:
            raise NetworkError(f"node {nid}: type must be 'reservoir' or 'junction'")

    pipe_ids = set()
    for raw in pipes:
        pid = str(raw.get("id", "")).strip()
        if not pid:
            raise NetworkError("every pipe needs a non-empty id")
        if pid in pipe_ids:
            raise NetworkError(f"duplicate pipe id '{pid}'")
        pipe_ids.add(pid)
        start = str(raw.get("from", "")).strip()
        end = str(raw.get("to", "")).strip()
        if start not in seen_ids or end not in seen_ids:
            raise NetworkError(f"pipe {pid} references an unknown node")
        net.add_pipe(
            pid, start, end,
            length=_num(raw.get("length"), "length", f"pipe {pid}"),
            diameter=_num(raw.get("diameter"), "diameter", f"pipe {pid}"),
            roughness=_num(raw.get("roughness"), "roughness", f"pipe {pid}"),
        )
    return net
