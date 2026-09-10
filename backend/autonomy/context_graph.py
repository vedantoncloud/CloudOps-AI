from dataclasses import dataclass, field
from threading import Lock


@dataclass(frozen=True)
class ResourceNode:
    resource_type: str
    resource_id: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ResourceEdge:
    source_id: str
    target_id: str
    relationship: str


class ContextGraph:
    """In-memory infrastructure relationship graph."""

    def __init__(self) -> None:
        self._nodes: dict[str, ResourceNode] = {}
        self._edges: list[ResourceEdge] = []
        self._lock = Lock()

    def add_node(
        self,
        resource_type: str,
        resource_id: str,
        metadata: dict | None = None,
    ) -> ResourceNode:
        if not resource_type or not resource_type.strip():
            raise ValueError("resource_type cannot be empty")
        if not resource_id or not resource_id.strip():
            raise ValueError("resource_id cannot be empty")

        node = ResourceNode(
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=metadata or {},
        )

        with self._lock:
            self._nodes[resource_id] = node

        return node

    def add_relationship(
        self,
        source_id: str,
        target_id: str,
        relationship: str,
    ) -> ResourceEdge:
        if not source_id or not source_id.strip():
            raise ValueError("source_id cannot be empty")
        if not target_id or not target_id.strip():
            raise ValueError("target_id cannot be empty")
        if not relationship or not relationship.strip():
            raise ValueError("relationship cannot be empty")

        with self._lock:
            if source_id not in self._nodes:
                raise ValueError(f"Source resource not found: {source_id}")
            if target_id not in self._nodes:
                raise ValueError(f"Target resource not found: {target_id}")

            edge = ResourceEdge(
                source_id=source_id,
                target_id=target_id,
                relationship=relationship,
            )

            if edge not in self._edges:
                self._edges.append(edge)

            return edge

    def get_node(self, resource_id: str) -> ResourceNode | None:
        with self._lock:
            return self._nodes.get(resource_id)

    def get_dependents(self, resource_id: str) -> list[ResourceNode]:
        with self._lock:
            dependent_ids = [
                edge.source_id
                for edge in self._edges
                if edge.target_id == resource_id
            ]
            return [
                self._nodes[node_id]
                for node_id in dict.fromkeys(dependent_ids)
                if node_id in self._nodes
            ]

    def get_dependencies(self, resource_id: str) -> list[ResourceNode]:
        with self._lock:
            dependency_ids = [
                edge.target_id
                for edge in self._edges
                if edge.source_id == resource_id
            ]
            return [
                self._nodes[node_id]
                for node_id in dict.fromkeys(dependency_ids)
                if node_id in self._nodes
            ]

    def get_edges(self) -> list[ResourceEdge]:
        with self._lock:
            return list(self._edges)

    def clear(self) -> None:
        with self._lock:
            self._nodes.clear()
            self._edges.clear()
