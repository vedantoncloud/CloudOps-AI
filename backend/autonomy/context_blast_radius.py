from autonomy.blast_radius import BlastRadiusAnalyzer
from autonomy.context_graph import ContextGraph


class ContextGraphBlastRadiusAnalyzer:
    """Build blast-radius input directly from the infrastructure context graph."""

    def __init__(self, graph: ContextGraph) -> None:
        self.graph = graph
        self.analyzer = BlastRadiusAnalyzer()

    def analyze(self, resource_id: str):
        node = self.graph.get_node(resource_id)
        if node is None:
            raise ValueError(f"Resource not found in context graph: {resource_id}")

        dependents = self.graph.get_dependents(resource_id)

        dependencies = []
        for dependent in dependents:
            dependencies.append(
                type(
                    "GraphDependency",
                    (),
                    {
                        "resource_type": dependent.resource_type,
                        "resource_id": dependent.resource_id,
                        "depends_on": (resource_id,),
                    },
                )()
            )

        affected_services = [
            dependent.resource_id
            for dependent in dependents
            if dependent.resource_type in {
                "service",
                "application",
            }
        ]

        return self.analyzer.analyze(
            resource_id=resource_id,
            dependencies=dependencies,
            affected_services=affected_services,
        )
