"""Unit tests for workflow graph validation."""

from __future__ import annotations

import pytest

from src.core.workflows.base import WorkflowDef, WorkflowEdgeDef, WorkflowNodeDef
from src.core.workflows.validation import validate_workflow_structure


def _minimal_workflow(**overrides) -> WorkflowDef:
    base = {
        "id": "wf1",
        "name": "Test",
        "description": "desc",
        "nodes": [
            WorkflowNodeDef(id="step_a", agent_id="log_analysis"),
            WorkflowNodeDef(id="step_b", agent_id="http_check"),
        ],
        "edges": [
            WorkflowEdgeDef(from_node="START", to_nodes=["step_a", "step_b"]),
        ],
    }
    base.update(overrides)
    return WorkflowDef(**base)


def test_validate_workflow_structure_accepts_valid_graph() -> None:
    validate_workflow_structure(_minimal_workflow())


def test_validate_workflow_structure_rejects_duplicate_node_ids() -> None:
    wf = _minimal_workflow(
        nodes=[
            WorkflowNodeDef(id="dup", agent_id="log_analysis"),
            WorkflowNodeDef(id="dup", agent_id="http_check"),
        ],
        edges=[WorkflowEdgeDef(from_node="START", to_nodes=["dup"])],
    )
    with pytest.raises(ValueError, match="Duplicate node ids"):
        validate_workflow_structure(wf)


def test_validate_workflow_structure_rejects_dangling_edge() -> None:
    wf = _minimal_workflow(
        edges=[WorkflowEdgeDef(from_node="START", to_nodes=["missing"])],
    )
    with pytest.raises(ValueError, match="unknown node"):
        validate_workflow_structure(wf)


def test_validate_workflow_structure_rejects_orphan_node() -> None:
    wf = _minimal_workflow(
        nodes=[
            WorkflowNodeDef(id="orphan", agent_id="log_analysis"),
            WorkflowNodeDef(id="used", agent_id="http_check"),
        ],
        edges=[WorkflowEdgeDef(from_node="START", to_nodes=["used"])],
    )
    with pytest.raises(ValueError, match="not referenced"):
        validate_workflow_structure(wf)


def test_validate_workflow_structure_rejects_unreachable_node() -> None:
    wf = _minimal_workflow(
        nodes=[
            WorkflowNodeDef(id="a", agent_id="log_analysis"),
            WorkflowNodeDef(id="b", agent_id="http_check"),
            WorkflowNodeDef(id="c", agent_id="ppl_generation"),
        ],
        edges=[
            WorkflowEdgeDef(from_node="START", to_nodes=["a"]),
            WorkflowEdgeDef(from_node="b", to_nodes=["c"]),
        ],
    )
    with pytest.raises(ValueError, match="not reachable from START"):
        validate_workflow_structure(wf)


def test_validate_workflow_structure_rejects_cycle() -> None:
    wf = _minimal_workflow(
        nodes=[
            WorkflowNodeDef(id="a", agent_id="log_analysis"),
            WorkflowNodeDef(id="b", agent_id="http_check"),
        ],
        edges=[
            WorkflowEdgeDef(from_node="START", to_nodes=["a"]),
            WorkflowEdgeDef(from_node="a", to_nodes=["b"]),
            WorkflowEdgeDef(from_node="b", to_nodes=["a"]),
        ],
    )
    with pytest.raises(ValueError, match="cycle"):
        validate_workflow_structure(wf)


def test_validate_workflow_structure_rejects_mutually_exclusive_edge_fields() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        WorkflowEdgeDef(
            from_node="START",
            to_nodes=["a"],
            routes={"X": "b"},
        )
