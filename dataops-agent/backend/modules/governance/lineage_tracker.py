import structlog
from datetime import datetime, timezone
from sqlalchemy import select, or_
from database import AsyncSessionLocal
from models.all_models import LineageNode, LineageEdge

log = structlog.get_logger()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class LineageTracker:
    """
    Manages data lineage graphs for AXIOM.

    Graph model:
      - LineageNode: a named asset (source, pipeline, table, report, API, model)
      - LineageEdge: directed relationship between two nodes (upstream → downstream)

    Traversal supports: upstream, downstream, or both directions.
    All methods are tenant-isolated.
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # 1. Add a lineage node
    # ------------------------------------------------------------------

    async def add_node(
        self,
        node_type: str,
        name: str,
        metadata: dict | None = None,
    ) -> dict:
        """
        Creates a LineageNode. Idempotent — if a node with the same
        (tenant_id, name, node_type) already exists, returns the existing one.

        node_type suggestions: source, pipeline, table, report, api, model, output

        Returns: { node_id, node_type, name, created: True/False }
        """
        log.info("lineage.add_node", tenant_id=self.tenant_id, name=name, node_type=node_type)
        try:
            async with AsyncSessionLocal() as db:
                # Idempotency check
                existing = await db.execute(
                    select(LineageNode).where(
                        LineageNode.tenant_id == self.tenant_id,
                        LineageNode.name == name,
                        LineageNode.node_type == node_type,
                    )
                )
                node = existing.scalar_one_or_none()
                if node:
                    return {
                        "node_id": str(node.id),
                        "node_type": node.node_type,
                        "name": node.name,
                        "created": False,
                        "message": "Node already exists",
                    }

                node = LineageNode(
                    tenant_id=self.tenant_id,
                    node_type=node_type,
                    name=name,
                    node_metadata=metadata or {},
                    created_at=utcnow(),
                )
                db.add(node)
                await db.commit()
                await db.refresh(node)

            log.info("lineage.add_node.done", node_id=str(node.id), name=name)
            return {
                "node_id": str(node.id),
                "node_type": node_type,
                "name": name,
                "metadata": metadata or {},
                "created": True,
            }
        except Exception as exc:
            log.error("lineage.add_node.error", error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 2. Add a lineage edge
    # ------------------------------------------------------------------

    async def add_edge(
        self,
        upstream_id: str,
        downstream_id: str,
        relationship_type: str = "produces",
    ) -> dict:
        """
        Creates a directed LineageEdge from upstream_id → downstream_id.
        Idempotent — duplicate edges (same upstream, downstream, type) are skipped.

        relationship_type suggestions:
          produces, transforms, reads_from, writes_to, depends_on, feeds

        Returns: { edge_id, upstream_id, downstream_id, relationship_type, created }
        """
        log.info(
            "lineage.add_edge",
            tenant_id=self.tenant_id,
            upstream=upstream_id,
            downstream=downstream_id,
        )
        try:
            async with AsyncSessionLocal() as db:
                # Verify both nodes exist and belong to this tenant
                for node_id, label in [(upstream_id, "upstream"), (downstream_id, "downstream")]:
                    check = await db.execute(
                        select(LineageNode).where(
                            LineageNode.id == node_id,
                            LineageNode.tenant_id == self.tenant_id,
                        )
                    )
                    if check.scalar_one_or_none() is None:
                        return {"error": f"{label} node {node_id} not found"}

                # Idempotency check
                existing = await db.execute(
                    select(LineageEdge).where(
                        LineageEdge.tenant_id == self.tenant_id,
                        LineageEdge.upstream_id == upstream_id,
                        LineageEdge.downstream_id == downstream_id,
                        LineageEdge.relationship_type == relationship_type,
                    )
                )
                edge = existing.scalar_one_or_none()
                if edge:
                    return {
                        "edge_id": str(edge.id),
                        "upstream_id": upstream_id,
                        "downstream_id": downstream_id,
                        "relationship_type": relationship_type,
                        "created": False,
                        "message": "Edge already exists",
                    }

                edge = LineageEdge(
                    tenant_id=self.tenant_id,
                    upstream_id=upstream_id,
                    downstream_id=downstream_id,
                    relationship_type=relationship_type,
                    created_at=utcnow(),
                )
                db.add(edge)
                await db.commit()
                await db.refresh(edge)

            log.info("lineage.add_edge.done", edge_id=str(edge.id))
            return {
                "edge_id": str(edge.id),
                "upstream_id": upstream_id,
                "downstream_id": downstream_id,
                "relationship_type": relationship_type,
                "created": True,
            }
        except Exception as exc:
            log.error("lineage.add_edge.error", error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 3. Get lineage for an asset (graph traversal)
    # ------------------------------------------------------------------

    async def get_lineage(
        self,
        asset_name: str,
        direction: str = "both",
        max_depth: int = 10,
    ) -> dict:
        """
        Traverses the lineage graph starting from the node named `asset_name`.

        direction:
          "upstream"   → walk backwards (what feeds this asset?)
          "downstream" → walk forwards  (what does this asset produce?)
          "both"       → full subgraph in both directions

        Uses iterative BFS to avoid recursion limits.
        Caps traversal at max_depth hops.

        Returns:
          {
            "root_node": { id, name, node_type },
            "nodes": [ { id, name, node_type, metadata } ],
            "edges": [ { edge_id, upstream_id, downstream_id, relationship_type } ],
            "depth_reached": N,
          }
        """
        log.info("lineage.get_lineage", asset_name=asset_name, direction=direction)
        try:
            async with AsyncSessionLocal() as db:
                # Find root node by name
                root_result = await db.execute(
                    select(LineageNode).where(
                        LineageNode.tenant_id == self.tenant_id,
                        LineageNode.name == asset_name,
                    )
                )
                root = root_result.scalars().first()
                if root is None:
                    return {"error": f"Asset '{asset_name}' not found in lineage graph"}

                # Load all nodes and edges for this tenant (for BFS)
                all_nodes_result = await db.execute(
                    select(LineageNode).where(LineageNode.tenant_id == self.tenant_id)
                )
                all_nodes = {str(n.id): n for n in all_nodes_result.scalars().all()}

                all_edges_result = await db.execute(
                    select(LineageEdge).where(LineageEdge.tenant_id == self.tenant_id)
                )
                all_edges = all_edges_result.scalars().all()

            # Build adjacency maps
            upstream_map: dict[str, list[LineageEdge]] = {}    # node_id → edges where node is downstream
            downstream_map: dict[str, list[LineageEdge]] = {}  # node_id → edges where node is upstream
            for edge in all_edges:
                downstream_map.setdefault(str(edge.upstream_id), []).append(edge)
                upstream_map.setdefault(str(edge.downstream_id), []).append(edge)

            # BFS
            visited_nodes: set[str] = set()
            visited_edges: set[str] = set()
            queue = [(str(root.id), 0)]
            max_depth_reached = 0

            while queue:
                current_id, depth = queue.pop(0)
                if current_id in visited_nodes or depth > max_depth:
                    continue
                visited_nodes.add(current_id)
                max_depth_reached = max(max_depth_reached, depth)

                if direction in ("upstream", "both"):
                    for edge in upstream_map.get(current_id, []):
                        eid = str(edge.id)
                        if eid not in visited_edges:
                            visited_edges.add(eid)
                        uid = str(edge.upstream_id)
                        if uid not in visited_nodes:
                            queue.append((uid, depth + 1))

                if direction in ("downstream", "both"):
                    for edge in downstream_map.get(current_id, []):
                        eid = str(edge.id)
                        if eid not in visited_edges:
                            visited_edges.add(eid)
                        did = str(edge.downstream_id)
                        if did not in visited_nodes:
                            queue.append((did, depth + 1))

            # Serialize results
            result_nodes = []
            for nid in visited_nodes:
                n = all_nodes.get(nid)
                if n:
                    result_nodes.append({
                        "id": str(n.id),
                        "name": n.name,
                        "node_type": n.node_type,
                        "metadata": n.node_metadata or {},
                        "created_at": n.created_at.isoformat() if n.created_at else None,
                    })

            result_edges = []
            for edge in all_edges:
                if str(edge.id) in visited_edges:
                    result_edges.append({
                        "edge_id": str(edge.id),
                        "upstream_id": str(edge.upstream_id),
                        "downstream_id": str(edge.downstream_id),
                        "relationship_type": edge.relationship_type,
                    })

            log.info(
                "lineage.get_lineage.done",
                asset_name=asset_name,
                nodes=len(result_nodes),
                edges=len(result_edges),
            )
            return {
                "root_node": {
                    "id": str(root.id),
                    "name": root.name,
                    "node_type": root.node_type,
                },
                "direction": direction,
                "nodes": result_nodes,
                "edges": result_edges,
                "node_count": len(result_nodes),
                "edge_count": len(result_edges),
                "depth_reached": max_depth_reached,
            }

        except Exception as exc:
            log.error("lineage.get_lineage.error", asset_name=asset_name, error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 4. Get full tenant graph
    # ------------------------------------------------------------------

    async def get_full_graph(self) -> dict:
        """
        Returns every node and edge for this tenant.
        Used for frontend graph visualization (React Flow / D3).

        Returns:
          { "nodes": [...], "edges": [...], "node_count": N, "edge_count": N }
        """
        log.info("lineage.get_full_graph", tenant_id=self.tenant_id)
        try:
            async with AsyncSessionLocal() as db:
                nodes_result = await db.execute(
                    select(LineageNode).where(LineageNode.tenant_id == self.tenant_id)
                )
                nodes = nodes_result.scalars().all()

                edges_result = await db.execute(
                    select(LineageEdge).where(LineageEdge.tenant_id == self.tenant_id)
                )
                edges = edges_result.scalars().all()

            return {
                "nodes": [
                    {
                        "id": str(n.id),
                        "name": n.name,
                        "node_type": n.node_type,
                        "metadata": n.node_metadata or {},
                        "created_at": n.created_at.isoformat() if n.created_at else None,
                    }
                    for n in nodes
                ],
                "edges": [
                    {
                        "edge_id": str(e.id),
                        "upstream_id": str(e.upstream_id),
                        "downstream_id": str(e.downstream_id),
                        "relationship_type": e.relationship_type,
                    }
                    for e in edges
                ],
                "node_count": len(nodes),
                "edge_count": len(edges),
            }
        except Exception as exc:
            log.error("lineage.get_full_graph.error", error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 5. Auto-register pipeline lineage
    # ------------------------------------------------------------------

    async def auto_register_pipeline_lineage(
        self, pipeline_id: str, pipeline_name: str, source_name: str
    ) -> dict:
        """
        Convenience method: creates the standard 3-node lineage chain
        for a pipeline automatically when it is registered or triggered.

            [source] → produces → [pipeline] → produces → [pipeline:output]

        Returns: { "nodes": [3], "edges": [2] }
        """
        log.info(
            "lineage.auto_register",
            pipeline_id=pipeline_id,
            pipeline_name=pipeline_name,
        )
        try:
            source_node = await self.add_node("source", source_name, {"auto": True})
            if "error" in source_node:
                return source_node

            pipeline_node = await self.add_node(
                "pipeline",
                pipeline_name,
                {"pipeline_id": pipeline_id, "auto": True},
            )
            if "error" in pipeline_node:
                return pipeline_node

            output_node = await self.add_node(
                "output",
                f"{pipeline_name}:output",
                {"pipeline_id": pipeline_id, "auto": True},
            )
            if "error" in output_node:
                return output_node

            edge1 = await self.add_edge(
                source_node["node_id"], pipeline_node["node_id"], "feeds"
            )
            edge2 = await self.add_edge(
                pipeline_node["node_id"], output_node["node_id"], "produces"
            )

            return {
                "nodes": [source_node, pipeline_node, output_node],
                "edges": [edge1, edge2],
                "pipeline_id": pipeline_id,
            }
        except Exception as exc:
            log.error("lineage.auto_register.error", error=str(exc))
            return {"error": str(exc)}