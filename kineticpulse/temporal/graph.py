"""Skeleton-graph utility for ST-GCN.

This is a faithful re-implementation of the ``coco_cut`` layout used by
the GajuuzZ TSSTG checkpoint
(https://github.com/GajuuzZ/Human-Falling-Detect-Tracks). We need to
match the exact node count (14), node ordering, and adjacency edges so
that ``TwoStreamSpatialTemporalGraph`` produces the same convolutional
``A`` tensor the released ``tsstg-model.pth`` weights were trained
against.

Node ordering (``coco_cut``):

    0  nose
    1  left_shoulder
    2  right_shoulder
    3  left_elbow
    4  right_elbow
    5  left_wrist
    6  right_wrist
    7  left_hip
    8  right_hip
    9  left_knee
    10 right_knee
    11 left_ankle
    12 right_ankle
    13 neck (= mean of left+right shoulder)

This is COCO-17 with the four facial keypoints (eyes + ears) dropped
and a synthetic neck joint appended at the end.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np


COCO_CUT_NUM_NODES = 14
COCO_CUT_CENTER = 13  # neck

# Edges as published in the upstream Graph definition. Order matters
# only for readability; adjacency is symmetrised inside ``_hop_distance``.
COCO_CUT_NEIGHBOR_LINK: Tuple[Tuple[int, int], ...] = (
    (6, 4), (4, 2), (2, 13), (13, 1), (5, 3), (3, 1),
    (12, 10), (10, 8), (8, 2),
    (11, 9), (9, 7), (7, 1),
    (13, 0),
)


class Graph:
    """Skeleton graph wrapper that exposes the partitioned adjacency
    tensor expected by :class:`StreamSpatialTemporalGraph`.

    Only the ``coco_cut`` layout is supported - that is the only layout
    the checkpoint was trained against. Three partition strategies are
    available; the released weights were trained with ``spatial`` and
    that is also our default.
    """

    def __init__(self,
                 layout: str = "coco_cut",
                 strategy: str = "spatial",
                 max_hop: int = 1,
                 dilation: int = 1) -> None:
        if layout != "coco_cut":
            raise ValueError(
                f"Unsupported layout {layout!r}; only 'coco_cut' matches "
                f"the released TSSTG checkpoint."
            )
        self.layout = layout
        self.strategy = strategy
        self.max_hop = max_hop
        self.dilation = dilation
        self.num_node = COCO_CUT_NUM_NODES
        self.center = COCO_CUT_CENTER

        self_link = [(i, i) for i in range(self.num_node)]
        self.edge = self_link + list(COCO_CUT_NEIGHBOR_LINK)
        self.hop_dis = self._hop_distance()
        self.A = self._build_adjacency(strategy)

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #

    def _hop_distance(self) -> np.ndarray:
        n = self.num_node
        adj = np.zeros((n, n), dtype=np.float32)
        for i, j in self.edge:
            adj[j, i] = 1.0
            adj[i, j] = 1.0
        hop_dis = np.full((n, n), np.inf, dtype=np.float32)
        transfer_mat = [np.linalg.matrix_power(adj, d)
                        for d in range(self.max_hop + 1)]
        arrive_mat = np.stack(transfer_mat) > 0
        for d in range(self.max_hop, -1, -1):
            hop_dis[arrive_mat[d]] = d
        return hop_dis

    @staticmethod
    def _normalize_digraph(adj: np.ndarray) -> np.ndarray:
        n = adj.shape[0]
        col_sum = adj.sum(axis=0)
        Dn = np.zeros((n, n), dtype=np.float32)
        for i in range(n):
            if col_sum[i] > 0:
                Dn[i, i] = col_sum[i] ** -1
        return adj @ Dn

    def _build_adjacency(self, strategy: str) -> np.ndarray:
        valid_hop = list(range(0, self.max_hop + 1, self.dilation))
        adjacency = np.zeros((self.num_node, self.num_node), dtype=np.float32)
        for hop in valid_hop:
            adjacency[self.hop_dis == hop] = 1.0
        normalize_adjacency = self._normalize_digraph(adjacency)

        if strategy == "uniform":
            A = np.zeros((1, self.num_node, self.num_node), dtype=np.float32)
            A[0] = normalize_adjacency
            return A

        if strategy == "distance":
            A = np.zeros((len(valid_hop), self.num_node, self.num_node),
                         dtype=np.float32)
            for i, hop in enumerate(valid_hop):
                A[i][self.hop_dis == hop] = normalize_adjacency[
                    self.hop_dis == hop]
            return A

        if strategy == "spatial":
            partitions = []
            for hop in valid_hop:
                a_root = np.zeros((self.num_node, self.num_node),
                                  dtype=np.float32)
                a_close = np.zeros((self.num_node, self.num_node),
                                   dtype=np.float32)
                a_further = np.zeros((self.num_node, self.num_node),
                                     dtype=np.float32)
                for i in range(self.num_node):
                    for j in range(self.num_node):
                        if self.hop_dis[j, i] != hop:
                            continue
                        d_j = self.hop_dis[j, self.center]
                        d_i = self.hop_dis[i, self.center]
                        if d_j == d_i:
                            a_root[j, i] = normalize_adjacency[j, i]
                        elif d_j > d_i:
                            a_close[j, i] = normalize_adjacency[j, i]
                        else:
                            a_further[j, i] = normalize_adjacency[j, i]
                if hop == 0:
                    partitions.append(a_root)
                else:
                    partitions.append(a_root + a_close)
                    partitions.append(a_further)
            return np.stack(partitions)

        raise ValueError(f"Unsupported partition strategy {strategy!r}")


__all__ = [
    "Graph",
    "COCO_CUT_NUM_NODES",
    "COCO_CUT_CENTER",
    "COCO_CUT_NEIGHBOR_LINK",
]
