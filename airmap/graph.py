"""Builds a logical "channel similarity" graph from one scan's networks.

This is NOT a physical connectivity graph -- Airmap has no way to know what
client devices are associated with which access point. An edge here means
two APs are close enough in channel to potentially interfere with each
other's transmissions, nothing about any device being connected to either.

Built with networkx rather than assembled as parallel node/edge lists: the
pairwise comparison + attribute storage this needs is exactly what
`nx.Graph` is for, and it keeps "which APs are adjacent to this one"
answerable via the graph API if a later phase needs it, instead of only
ever having a flat edge list.
"""

from __future__ import annotations

from typing import Any

import networkx as nx

# 2.4GHz channels are 5MHz apart but each occupies ~22MHz, so channels
# within a few of each other still overlap in frequency; channels 5+ apart
# (the classic 1/6/11 layout) are the standard "non-overlapping" set.
_WIFI_24GHZ_NON_OVERLAP_DISTANCE = 5
_STRONG_WEIGHT = 1.0
_WEAK_WEIGHT = 0.4


def _edge_for_pair(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, str] | None:
    """Returns `(weight, reason)` if `a` and `b` should be connected, else None.

    Never connects APs on different bands -- a 2.4GHz and a 5GHz radio
    cannot interfere with each other regardless of channel number. 6GHz is
    treated the same as 5GHz below (only an exact channel match counts):
    the spec only calls out 2.4GHz/5GHz explicitly, but 6GHz shares 5GHz's
    non-overlapping channel plan, so the same rule is the natural extension
    rather than leaving 6GHz APs with no edge logic at all.
    """
    if a["band"] != b["band"]:
        return None

    channel_diff = abs(a["channel"] - b["channel"])

    if a["band"] == "2.4GHz":
        if channel_diff == 0:
            return _STRONG_WEIGHT, "same_channel"
        if channel_diff < _WIFI_24GHZ_NON_OVERLAP_DISTANCE:
            return _WEAK_WEIGHT, "partial_overlap"
        return None

    if channel_diff == 0:
        return _STRONG_WEIGHT, "same_channel"
    return None


def build_similarity_graph(networks: list[dict[str, Any]]) -> nx.Graph:
    """Builds the channel-similarity graph for one scan's networks.

    Nodes are keyed by BSSID (unique per AP within one scan) and carry the
    full reading as attributes; edges carry `weight` and `reason`.
    """
    graph: nx.Graph = nx.Graph()
    for network in networks:
        graph.add_node(network["bssid"], **network)

    for i, a in enumerate(networks):
        for b in networks[i + 1 :]:
            edge = _edge_for_pair(a, b)
            if edge is not None:
                weight, reason = edge
                graph.add_edge(a["bssid"], b["bssid"], weight=weight, reason=reason)

    return graph


def graph_to_json(graph: nx.Graph) -> dict[str, Any]:
    """Serializes a similarity graph to the plain nodes/edges shape the API returns."""
    nodes = [{"id": bssid, **attrs} for bssid, attrs in graph.nodes(data=True)]
    edges = [
        {"source": u, "target": v, "weight": attrs["weight"], "reason": attrs["reason"]}
        for u, v, attrs in graph.edges(data=True)
    ]
    return {"nodes": nodes, "edges": edges}


def build_graph_data(networks: list[dict[str, Any]]) -> dict[str, Any]:
    """One-shot: a scan's networks -> the JSON-ready `{"nodes", "edges"}` shape."""
    return graph_to_json(build_similarity_graph(networks))
