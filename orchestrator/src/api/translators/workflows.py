from __future__ import annotations

from src.api.models.schemas import WorkflowEdgeResource, WorkflowNodeResource, WorkflowResource
from src.core.workflows import WorkflowDef, WorkflowEdgeDef, WorkflowNodeDef


def workflow_def_to_resource(workflow: WorkflowDef) -> WorkflowResource:
    return WorkflowResource(
        id=workflow.id,
        name=workflow.name,
        description=workflow.description,
        nodes=[
            WorkflowNodeResource(
                id=n.id,
                type=n.type,
                agent_id=n.agent_id,
                objective=n.objective,
            )
            for n in workflow.nodes
        ],
        edges=[
            WorkflowEdgeResource(
                from_node=e.from_node,
                to_nodes=e.to_nodes,
                routes=e.routes,
            )
            for e in workflow.edges
        ],
    )


def resource_to_workflow_def(resource: WorkflowResource) -> WorkflowDef:
    return WorkflowDef(
        id=resource.id,
        name=resource.name,
        description=resource.description,
        nodes=[
            WorkflowNodeDef(
                id=n.id,
                type=n.type,
                agent_id=n.agent_id,
                objective=n.objective,
            )
            for n in resource.nodes
        ],
        edges=[
            WorkflowEdgeDef(
                from_node=e.from_node,
                to_nodes=e.to_nodes or [],
                routes=e.routes,
            )
            for e in resource.edges
        ],
    )
