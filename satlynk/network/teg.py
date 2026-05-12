"""Time-Expanded Graph (TEG) — OBS1 核心数据结构.

将时变网络 L_ij(t) 展开为静态有向图 G^TE：
  - 顶点 (i, k)：节点 i 在时间片 k
  - 存储边 (i,k) → (i,k+1)：数据留在原地，cost = 存储开销
  - 传输边 (i,k) → (j,k+Δ)：数据经链路传输，Δ 由数据量/带宽决定
  - 计算边 (i,k) → (i,k+Δ_comp)：在节点 i 上执行计算

原问题退化为该静态图上的容量受限多商品流 + 任务落点选择。

Key insight: 时间被 "烘焙进拓扑"，时变约束变成了图结构约束。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Set
from enum import Enum
import numpy as np
from heapq import heappush, heappop

from satlynk.network.contact_plan import ContactPlan, ContactWindow


class EdgeType(str, Enum):
    """TEG edge types."""
    STORE = "store"        # Data stays at same node: (i,k) → (i,k+1)
    TRANSFER = "transfer"  # Data moves across link: (i,k) → (j,k+Δ)
    COMPUTE = "compute"    # Computation happens: (i,k) → (i,k+Δ_comp)


@dataclass(frozen=True)
class TEGNode:
    """A vertex in the time-expanded graph: (satellite, time_slot)."""
    sat_id: int      # Satellite index
    time_slot: int   # Discrete time slot index

    def __repr__(self):
        return f"({self.sat_id}, t{self.time_slot})"


@dataclass
class TEGEdge:
    """A directed edge in the time-expanded graph."""
    src: TEGNode
    dst: TEGNode
    edge_type: EdgeType
    capacity_bytes: int     # Max data that can traverse this edge
    cost: float             # Cost metric (time, energy, or combined)
    transfer_time_s: float  # Physical duration of this edge
    window_id: int = -1     # Index into ContactPlan.windows (for TRANSFER edges)

    @property
    def src_sat(self) -> int:
        return self.src.sat_id

    @property
    def dst_sat(self) -> int:
        return self.dst.sat_id

    def __repr__(self):
        return f"Edge({self.src}→{self.dst}, {self.edge_type.value}, cap={self.capacity_bytes/1e6:.1f}MB)"


@dataclass
class TEGPath:
    """A path through the time-expanded graph."""
    edges: List[TEGEdge]
    total_cost: float
    total_time_s: float
    hops: int              # Number of TRANSFER edges
    nodes_visited: List[int]  # Satellite IDs in order

    @property
    def departure_slot(self) -> int:
        return self.edges[0].src.time_slot if self.edges else -1

    @property
    def arrival_slot(self) -> int:
        return self.edges[-1].dst.time_slot if self.edges else -1

    @property
    def bottleneck_capacity(self) -> int:
        """Minimum capacity along the path."""
        if not self.edges:
            return 0
        return min(e.capacity_bytes for e in self.edges if e.edge_type == EdgeType.TRANSFER)


class TimeExpandedGraph:
    """
    Time-Expanded Graph constructed from a ContactPlan.

    Construction:
        1. Discretize [0, H] into K = H/Δt time slots
        2. For each node i, create K vertices: (i, 0), (i, 1), ..., (i, K-1)
        3. Add STORE edges: (i,k) → (i,k+1) for all i,k
        4. For each ContactWindow w(i,j,[t_s,t_e]):
           Add TRANSFER edges (i,k) → (j,k+Δ) for k ∈ [t_s/Δt, t_e/Δt]
           where Δ = ceil(data_size / (rate * Δt))

    The graph supports:
        - Shortest path (min-cost route for a single data packet)
        - Multi-commodity flow (concurrent tasks competing for bandwidth)
        - Reachability analysis (which nodes can receive data from source by deadline)
    """

    def __init__(self, num_sats: int, num_slots: int, dt_s: float):
        """
        Args:
            num_sats: Number of satellites
            num_slots: Number of time slots K
            dt_s: Duration of each time slot (seconds)
        """
        self.num_sats = num_sats
        self.num_slots = num_slots
        self.dt_s = dt_s
        self.horizon_s = num_slots * dt_s

        # Adjacency list: node → list of outgoing edges
        self._adj: Dict[TEGNode, List[TEGEdge]] = {}
        # Reverse adjacency for backward search
        self._radj: Dict[TEGNode, List[TEGEdge]] = {}
        # All edges
        self._edges: List[TEGEdge] = []
        # Node index for fast access
        self._nodes: Set[TEGNode] = set()

        # Statistics
        self.num_store_edges = 0
        self.num_transfer_edges = 0

    @classmethod
    def from_contact_plan(
        cls,
        contact_plan: ContactPlan,
        num_sats: int,
        horizon_s: float,
        dt_s: float = 10.0,
        data_rate_bps: float = 50e6,
        store_cost: float = 0.1,
        transfer_cost_per_s: float = 1.0,
    ) -> 'TimeExpandedGraph':
        """
        Build TEG from a ContactPlan.

        Args:
            contact_plan: Precomputed communication windows
            num_sats: Total number of satellites
            horizon_s: Planning horizon (seconds)
            dt_s: Time slot granularity (seconds). Smaller = more precise but larger graph.
            data_rate_bps: Link data rate (bit/s)
            store_cost: Cost per STORE edge (penalizes waiting)
            transfer_cost_per_s: Cost per second of transfer time
        """
        num_slots = int(horizon_s / dt_s) + 1
        teg = cls(num_sats, num_slots, dt_s)

        # 1. Create all nodes
        for i in range(num_sats):
            for k in range(num_slots):
                node = TEGNode(sat_id=i, time_slot=k)
                teg._nodes.add(node)
                teg._adj[node] = []
                teg._radj[node] = []

        # 2. Add STORE edges: (i,k) → (i,k+1) for all i, k<K-1
        for i in range(num_sats):
            for k in range(num_slots - 1):
                src = TEGNode(i, k)
                dst = TEGNode(i, k + 1)
                edge = TEGEdge(
                    src=src, dst=dst,
                    edge_type=EdgeType.STORE,
                    capacity_bytes=int(1e18),  # Unlimited storage capacity
                    cost=store_cost,
                    transfer_time_s=dt_s,
                )
                teg._add_edge(edge)
                teg.num_store_edges += 1

        # 3. Add TRANSFER edges from contact windows
        for w_idx, window in enumerate(contact_plan.windows):
            # Determine which time slots this window covers
            k_start = max(0, int(window.start_s / dt_s))
            k_end = min(num_slots - 1, int(window.end_s / dt_s))

            # Transfer duration for one time slot worth of data
            # Capacity per slot: rate * dt_s / 8 bytes
            capacity_per_slot = int(data_rate_bps * dt_s / 8)

            for k in range(k_start, k_end):
                # Edge from src to dst (and reverse, since links are bidirectional)
                for (s, d) in [(window.src, window.dst), (window.dst, window.src)]:
                    src_node = TEGNode(s, k)
                    # Transfer takes 1 time slot (data arrives at k+1)
                    dst_node = TEGNode(d, k + 1)

                    if dst_node.time_slot >= num_slots:
                        continue

                    edge = TEGEdge(
                        src=src_node, dst=dst_node,
                        edge_type=EdgeType.TRANSFER,
                        capacity_bytes=capacity_per_slot,
                        cost=transfer_cost_per_s * dt_s,
                        transfer_time_s=dt_s,
                        window_id=w_idx,
                    )
                    teg._add_edge(edge)
                    teg.num_transfer_edges += 1

        return teg

    def _add_edge(self, edge: TEGEdge):
        """Add an edge to the graph."""
        self._adj[edge.src].append(edge)
        self._radj[edge.dst].append(edge)
        self._edges.append(edge)

    # === Query API ===

    @property
    def num_nodes(self) -> int:
        return len(self._nodes)

    @property
    def num_edges(self) -> int:
        return len(self._edges)

    def get_node(self, sat_id: int, time_slot: int) -> TEGNode:
        """Get a specific TEG node."""
        return TEGNode(sat_id, time_slot)

    def time_to_slot(self, t_s: float) -> int:
        """Convert continuous time to discrete slot index."""
        return min(int(t_s / self.dt_s), self.num_slots - 1)

    def slot_to_time(self, k: int) -> float:
        """Convert slot index to continuous time."""
        return k * self.dt_s

    def get_outgoing(self, node: TEGNode) -> List[TEGEdge]:
        """Get all outgoing edges from a node."""
        return self._adj.get(node, [])

    def get_incoming(self, node: TEGNode) -> List[TEGEdge]:
        """Get all incoming edges to a node."""
        return self._radj.get(node, [])

    def get_transfer_edges_at(self, time_slot: int) -> List[TEGEdge]:
        """Get all transfer edges departing at a given time slot."""
        edges = []
        for i in range(self.num_sats):
            node = TEGNode(i, time_slot)
            for e in self._adj.get(node, []):
                if e.edge_type == EdgeType.TRANSFER:
                    edges.append(e)
        return edges

    # === Routing Algorithms ===

    def shortest_path(
        self,
        src_sat: int,
        dst_sat: int,
        earliest_departure_s: float,
        data_bytes: int = 0,
        latest_arrival_s: Optional[float] = None,
    ) -> Optional[TEGPath]:
        """
        Find minimum-cost path from (src_sat, t_depart) to (dst_sat, t_arrive).

        Uses Dijkstra on the TEG. Transfer edges with insufficient capacity
        for the given data_bytes are excluded.

        Args:
            src_sat: Source satellite index
            dst_sat: Destination satellite index
            earliest_departure_s: Earliest departure time
            data_bytes: Data size to transfer (for capacity filtering)
            latest_arrival_s: Deadline (None = horizon end)

        Returns:
            TEGPath or None if no path exists
        """
        k_start = self.time_to_slot(earliest_departure_s)
        k_end = self.time_to_slot(latest_arrival_s) if latest_arrival_s else self.num_slots - 1

        # Dijkstra
        start = TEGNode(src_sat, k_start)
        dist: Dict[TEGNode, float] = {start: 0.0}
        prev: Dict[TEGNode, Tuple[TEGNode, TEGEdge]] = {}
        heap = [(0.0, id(start), start)]  # (cost, tiebreak, node)
        visited: Set[TEGNode] = set()

        while heap:
            cost, _, node = heappop(heap)

            if node in visited:
                continue
            visited.add(node)

            # Check if we've reached destination
            if node.sat_id == dst_sat and node.time_slot >= k_start:
                # Reconstruct path
                if node == start and src_sat == dst_sat:
                    # Already at destination
                    return TEGPath(edges=[], total_cost=0, total_time_s=0,
                                   hops=0, nodes_visited=[src_sat])
                if node != start:
                    return self._reconstruct_path(start, node, prev)

            # Explore neighbors
            for edge in self._adj.get(node, []):
                neighbor = edge.dst

                # Skip if beyond deadline
                if neighbor.time_slot > k_end:
                    continue

                # Skip if insufficient capacity
                if edge.edge_type == EdgeType.TRANSFER and data_bytes > 0:
                    if edge.capacity_bytes < data_bytes:
                        continue

                new_cost = cost + edge.cost
                if neighbor not in dist or new_cost < dist[neighbor]:
                    dist[neighbor] = new_cost
                    prev[neighbor] = (node, edge)
                    heappush(heap, (new_cost, id(neighbor), neighbor))

        # Check if we reached any destination slot
        best_arrival = None
        best_cost = float('inf')
        for k in range(k_start, k_end + 1):
            dest = TEGNode(dst_sat, k)
            if dest in dist and dist[dest] < best_cost:
                best_cost = dist[dest]
                best_arrival = dest

        if best_arrival is not None and best_arrival != start:
            return self._reconstruct_path(start, best_arrival, prev)

        return None

    def earliest_arrival(
        self,
        src_sat: int,
        dst_sat: int,
        departure_s: float,
        data_bytes: int = 0,
    ) -> Optional[float]:
        """
        Find the earliest time data can arrive at dst from src.

        Optimizes for arrival time (not cost). More efficient than
        shortest_path when we only need timing.
        """
        k_start = self.time_to_slot(departure_s)

        # BFS-like: process slots in order (exploits DAG-like structure)
        # earliest[node] = earliest arrival slot at that node
        earliest: Dict[int, int] = {}  # sat_id → earliest slot
        earliest[src_sat] = k_start

        # Process slot by slot
        for k in range(k_start, self.num_slots):
            # Check all nodes at this slot
            for sat in list(earliest.keys()):
                if earliest[sat] > k:
                    continue  # Not yet arrived at this sat

                node = TEGNode(sat, k)
                for edge in self._adj.get(node, []):
                    next_sat = edge.dst.sat_id
                    next_slot = edge.dst.time_slot

                    # Capacity check for transfer edges
                    if edge.edge_type == EdgeType.TRANSFER and data_bytes > 0:
                        if edge.capacity_bytes < data_bytes:
                            continue

                    if next_sat not in earliest or next_slot < earliest[next_sat]:
                        earliest[next_sat] = next_slot

            # Early termination
            if dst_sat in earliest and earliest[dst_sat] <= k:
                return self.slot_to_time(earliest[dst_sat])

        if dst_sat in earliest:
            return self.slot_to_time(earliest[dst_sat])
        return None

    def reachable_nodes(
        self,
        src_sat: int,
        departure_s: float,
        deadline_s: float,
    ) -> Dict[int, float]:
        """
        Find all satellites reachable from src within deadline.

        Returns: Dict[sat_id → earliest_arrival_time_s]
        """
        k_start = self.time_to_slot(departure_s)
        k_end = self.time_to_slot(deadline_s)

        # BFS from source
        earliest: Dict[int, int] = {src_sat: k_start}

        for k in range(k_start, min(k_end + 1, self.num_slots)):
            for sat in list(earliest.keys()):
                if earliest[sat] > k:
                    continue

                node = TEGNode(sat, k)
                for edge in self._adj.get(node, []):
                    next_sat = edge.dst.sat_id
                    next_slot = edge.dst.time_slot

                    if next_slot > k_end:
                        continue

                    if next_sat not in earliest or next_slot < earliest[next_sat]:
                        earliest[next_sat] = next_slot

        return {sat: self.slot_to_time(slot) for sat, slot in earliest.items()}

    def all_paths(
        self,
        src_sat: int,
        dst_sat: int,
        departure_s: float,
        deadline_s: float,
        max_hops: int = 5,
        max_paths: int = 10,
    ) -> List[TEGPath]:
        """
        Find multiple distinct paths (k-shortest paths).

        Useful for understanding routing alternatives and redundancy.
        Uses Yen's algorithm variant on the TEG.
        """
        paths = []

        # Find first shortest path
        first = self.shortest_path(src_sat, dst_sat, departure_s,
                                   latest_arrival_s=deadline_s)
        if first is None:
            return []
        paths.append(first)

        if max_paths <= 1:
            return paths

        # Simple approach: find paths with different intermediate nodes
        # (Full Yen's is expensive on large TEGs)
        k_start = self.time_to_slot(departure_s)
        k_end = self.time_to_slot(deadline_s)

        # Try forcing through each intermediate satellite
        for relay in range(self.num_sats):
            if relay == src_sat or relay == dst_sat:
                continue
            if len(paths) >= max_paths:
                break

            # src → relay
            leg1 = self.shortest_path(src_sat, relay, departure_s,
                                      latest_arrival_s=deadline_s)
            if leg1 is None:
                continue

            # relay → dst (depart after leg1 arrives)
            relay_arrive_s = self.slot_to_time(leg1.arrival_slot)
            leg2 = self.shortest_path(relay, dst_sat, relay_arrive_s,
                                      latest_arrival_s=deadline_s)
            if leg2 is None:
                continue

            # Combine
            combined = TEGPath(
                edges=leg1.edges + leg2.edges,
                total_cost=leg1.total_cost + leg2.total_cost,
                total_time_s=self.slot_to_time(leg2.arrival_slot) - departure_s,
                hops=leg1.hops + leg2.hops,
                nodes_visited=leg1.nodes_visited + leg2.nodes_visited[1:],
            )
            paths.append(combined)

        # Sort by cost
        paths.sort(key=lambda p: p.total_cost)
        return paths[:max_paths]

    # === Analysis ===

    def connectivity_matrix(self, time_slot: int) -> np.ndarray:
        """
        Get N×N connectivity matrix at a specific time slot.

        Returns: matrix[i,j] = 1 if transfer edge (i,k)→(j,k+1) exists, else 0.
        """
        matrix = np.zeros((self.num_sats, self.num_sats), dtype=np.int8)
        for i in range(self.num_sats):
            node = TEGNode(i, time_slot)
            for edge in self._adj.get(node, []):
                if edge.edge_type == EdgeType.TRANSFER:
                    matrix[i, edge.dst.sat_id] = 1
        return matrix

    def bandwidth_utilization(self) -> Dict[int, float]:
        """
        Analyze potential bandwidth utilization per time slot.

        Returns: Dict[time_slot → total_available_capacity_bytes]
        """
        utilization = {}
        for k in range(self.num_slots):
            total_cap = sum(
                e.capacity_bytes
                for e in self.get_transfer_edges_at(k)
            )
            utilization[k] = total_cap
        return utilization

    def graph_stats(self) -> Dict[str, any]:
        """Return summary statistics of the TEG."""
        transfer_caps = [e.capacity_bytes for e in self._edges
                         if e.edge_type == EdgeType.TRANSFER]
        return {
            'num_sats': self.num_sats,
            'num_slots': self.num_slots,
            'dt_s': self.dt_s,
            'horizon_s': self.horizon_s,
            'num_nodes': self.num_nodes,
            'num_edges': self.num_edges,
            'num_store_edges': self.num_store_edges,
            'num_transfer_edges': self.num_transfer_edges,
            'avg_transfer_capacity_mb': np.mean(transfer_caps) / 1e6 if transfer_caps else 0,
            'total_transfer_capacity_gb': sum(transfer_caps) / 1e9 if transfer_caps else 0,
        }

    # === Internal ===

    def _reconstruct_path(
        self, start: TEGNode, end: TEGNode,
        prev: Dict[TEGNode, Tuple[TEGNode, TEGEdge]]
    ) -> TEGPath:
        """Reconstruct path from Dijkstra predecessors."""
        edges = []
        node = end
        while node != start:
            if node not in prev:
                break
            parent, edge = prev[node]
            edges.append(edge)
            node = parent

        edges.reverse()

        # Compute stats
        hops = sum(1 for e in edges if e.edge_type == EdgeType.TRANSFER)
        total_cost = sum(e.cost for e in edges)
        total_time = self.slot_to_time(end.time_slot) - self.slot_to_time(start.time_slot)

        # Extract visited satellites
        nodes_visited = [start.sat_id]
        for e in edges:
            if e.dst.sat_id != nodes_visited[-1]:
                nodes_visited.append(e.dst.sat_id)

        return TEGPath(
            edges=edges,
            total_cost=total_cost,
            total_time_s=total_time,
            hops=hops,
            nodes_visited=nodes_visited,
        )
