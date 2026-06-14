"""Validate workflow definitions on save."""

from __future__ import annotations

from collections import defaultdict

from src.core.workflows.base import WorkflowDef
from src.storage.interface import StorageGateway


def _build_adjacency(workflow: WorkflowDef) -> dict[str, list[str]]:
    """Build directed edges for cycle and reachability checks."""
    adj: dict[str, list[str]] = defaultdict(list)

    for edge in workflow.edges:
        if edge.from_node == "START":
            nodes = edge.to_nodes
            if not nodes:
                continue
            for i, node_id in enumerate(nodes):
                if i == 0:
                    adj["START"].append(node_id)
                else:
                    adj[nodes[i - 1]].append(node_id)
        elif edge.routes:
            for target in edge.routes.values():
                adj[edge.from_node].append(target)
        else:
            nodes = edge.to_nodes
            if not nodes:
                continue
            adj[edge.from_node].append(nodes[0])
            for i in range(1, len(nodes)):
                adj[nodes[i - 1]].append(nodes[i])

    return adj


def _has_cycle(adj: dict[str, list[str]], node_ids: set[str]) -> bool:
    visited: set[str] = set()
    stack: set[str] = set()

    def dfs(node: str) -> bool:
        if node in stack:
            return True
        if node in visited or node == "START":
            return False
        visited.add(node)
        stack.add(node)
        for neighbor in adj.get(node, []):
            if neighbor in node_ids and dfs(neighbor):
                return True
        stack.remove(node)
        return False

    for node_id in node_ids:
        if dfs(node_id):
            return True
    return False


def _reachable_from_start(adj: dict[str, list[str]], node_ids: set[str]) -> set[str]:
    reachable: set[str] = set()
    stack = list(adj.get("START", []))
    while stack:
        node = stack.pop()
        if node not in node_ids or node in reachable:
            continue
        reachable.add(node)
        stack.extend(adj.get(node, []))
    return reachable


def _nodes_referenced_in_edges(workflow: WorkflowDef) -> set[str]:
    referenced: set[str] = set()
    for edge in workflow.edges:
        if edge.from_node != "START":
            referenced.add(edge.from_node)
        referenced.update(edge.to_nodes)
        if edge.routes:
            referenced.update(edge.routes.values())
    return referenced


def validate_workflow_structure(workflow: WorkflowDef) -> None:
    """Raise ValueError when the workflow graph is invalid."""
    node_ids = [n.id for n in workflow.nodes]
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("Duplicate node ids in workflow")

    node_id_set = set(node_ids)

    if not workflow.edges:
        raise ValueError("Workflow must define at least one edge")

    for edge in workflow.edges:
        if edge.from_node != "START" and edge.from_node not in node_id_set:
            raise ValueError(f"Edge references unknown from_node: {edge.from_node!r}")
        for target in edge.to_nodes:
            if target not in node_id_set:
                raise ValueError(f"Edge references unknown node: {target!r}")
        if edge.routes:
            for target in edge.routes.values():
                if target not in node_id_set:
                    raise ValueError(f"Edge route references unknown node: {target!r}")

    referenced = _nodes_referenced_in_edges(workflow)
    orphans = node_id_set - referenced
    if orphans:
        raise ValueError(f"Nodes not referenced in any edge: {sorted(orphans)}")

    unreferenced_sources = referenced - node_id_set
    if unreferenced_sources:
        raise ValueError(f"Edge references undeclared nodes: {sorted(unreferenced_sources)}")

    adj = _build_adjacency(workflow)
    reachable = _reachable_from_start(adj, node_id_set)
    unreachable = node_id_set - reachable
    if unreachable:
        raise ValueError(f"Nodes not reachable from START: {sorted(unreachable)}")

    if _has_cycle(adj, node_id_set):
        raise ValueError("Workflow graph contains a cycle")


def _sequential_node_order(workflow: WorkflowDef) -> list[str]:
    """Return workflow node ids in START-to-terminal order for sequential chains."""
    adj = _build_adjacency(workflow)
    order: list[str] = []
    current = "START"
    visited: set[str] = set()
    while True:
        successors = adj.get(current, [])
        if not successors:
            break
        next_node = successors[0]
        if next_node in visited:
            break
        order.append(next_node)
        visited.add(next_node)
        current = next_node
    return order


async def validate_workflow_instance(
    workflow: WorkflowDef,
    *,
    tenant_slug: str,
    storage: StorageGateway,
) -> None:
    """Raise ValueError when workflow fails structural or tenant validation."""
    validate_workflow_structure(workflow)

    for node in workflow.nodes:
        row = await storage.tenant_agents.get_for_tenant(tenant_slug, node.agent_id)
        if row is None:
            raise ValueError(f"Unknown agent_id referenced by node {node.id!r}: {node.agent_id!r}")
