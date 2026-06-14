"""Two-Stream Spatial-Temporal Graph CNN model definition.

The module topology mirrors the GajuuzZ ``Actionsrecognition.Models``
implementation byte-for-byte (same layer counts, channel widths,
kernel sizes, BatchNorm / Dropout placement, ``edge_importance``
ParameterList, and final ``fcn`` linear projection) so the released
``tsstg-model.pth`` ``state_dict`` loads cleanly with ``strict=True``.

Reference: Yan et al., "Spatial Temporal Graph Convolutional Networks
for Skeleton-Based Action Recognition", AAAI 2018.
"""

from __future__ import annotations

from typing import Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

from kineticpulse.temporal.graph import Graph


class GraphConvolution(nn.Module):
    """Single graph convolution: temporal 1D conv expanded over the
    spatial kernel, then einsum-reduced with the adjacency tensor."""

    def __init__(self,
                 in_channels: int,
                 out_channels: int,
                 kernel_size: int,
                 t_kernel_size: int = 1,
                 t_stride: int = 1,
                 t_padding: int = 0,
                 t_dilation: int = 1,
                 bias: bool = True) -> None:
        super().__init__()
        self.kernel_size = kernel_size
        self.conv = nn.Conv2d(
            in_channels,
            out_channels * kernel_size,
            kernel_size=(t_kernel_size, 1),
            padding=(t_padding, 0),
            stride=(t_stride, 1),
            dilation=(t_dilation, 1),
            bias=bias,
        )

    def forward(self, x: torch.Tensor, A: torch.Tensor) -> torch.Tensor:
        x = self.conv(x)
        n, kc, t, v = x.size()
        x = x.view(n, self.kernel_size, kc // self.kernel_size, t, v)
        x = torch.einsum("nkctv,kvw->nctw", (x, A))
        return x.contiguous()


class StGcnBlock(nn.Module):
    """One ST-GCN layer: graph conv -> temporal BN+ReLU+Conv+BN+Dropout
    with an optional residual shortcut.

    The submodule names (``gcn``, ``tcn``, ``residual``, ``relu``) are
    intentionally identical to the upstream so the released checkpoint
    state_dict matches ours.
    """

    def __init__(self,
                 in_channels: int,
                 out_channels: int,
                 kernel_size: Tuple[int, int],
                 stride: int = 1,
                 dropout: float = 0.0,
                 residual: bool = True) -> None:
        super().__init__()
        assert len(kernel_size) == 2
        assert kernel_size[0] % 2 == 1
        padding = ((kernel_size[0] - 1) // 2, 0)

        self.gcn = GraphConvolution(in_channels, out_channels, kernel_size[1])
        self.tcn = nn.Sequential(
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
            nn.Conv2d(
                out_channels, out_channels,
                (kernel_size[0], 1),
                (stride, 1),
                padding,
            ),
            nn.BatchNorm2d(out_channels),
            nn.Dropout(dropout, inplace=True),
        )

        if not residual:
            self.residual = lambda x: 0
        elif (in_channels == out_channels) and (stride == 1):
            self.residual = lambda x: x
        else:
            self.residual = nn.Sequential(
                nn.Conv2d(in_channels, out_channels, kernel_size=1,
                          stride=(stride, 1)),
                nn.BatchNorm2d(out_channels),
            )
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x: torch.Tensor, A: torch.Tensor) -> torch.Tensor:
        res = self.residual(x)
        x = self.gcn(x, A)
        x = self.tcn(x) + res
        return self.relu(x)


class StreamSpatialTemporalGraph(nn.Module):
    """Single-stream ST-GCN backbone.

    With ``num_class=None`` it returns the global-pooled feature vector,
    which is what the two-stream wrapper concatenates before its final
    linear classifier. The released checkpoint instantiates two of
    these (one for points, one for motion) with ``num_class=None``.
    """

    def __init__(self,
                 in_channels: int,
                 graph_args: dict,
                 num_class: int = None,
                 edge_importance_weighting: bool = True,
                 **kwargs) -> None:
        super().__init__()

        graph = Graph(**graph_args)
        A = torch.tensor(graph.A, dtype=torch.float32, requires_grad=False)
        self.register_buffer("A", A)

        spatial_kernel_size = A.size(0)
        temporal_kernel_size = 9
        kernel_size = (temporal_kernel_size, spatial_kernel_size)
        kwargs0 = {k: v for k, v in kwargs.items() if k != "dropout"}

        self.data_bn = nn.BatchNorm1d(in_channels * A.size(1))

        # 10 ST-GCN layers, exactly matching the upstream channel widths.
        self.st_gcn_networks = nn.ModuleList((
            StGcnBlock(in_channels, 64, kernel_size, 1,
                       residual=False, **kwargs0),
            StGcnBlock(64, 64, kernel_size, 1, **kwargs),
            StGcnBlock(64, 64, kernel_size, 1, **kwargs),
            StGcnBlock(64, 64, kernel_size, 1, **kwargs),
            StGcnBlock(64, 128, kernel_size, 2, **kwargs),
            StGcnBlock(128, 128, kernel_size, 1, **kwargs),
            StGcnBlock(128, 128, kernel_size, 1, **kwargs),
            StGcnBlock(128, 256, kernel_size, 2, **kwargs),
            StGcnBlock(256, 256, kernel_size, 1, **kwargs),
            StGcnBlock(256, 256, kernel_size, 1, **kwargs),
        ))

        if edge_importance_weighting:
            self.edge_importance = nn.ParameterList([
                nn.Parameter(torch.ones(A.size()))
                for _ in self.st_gcn_networks
            ])
        else:
            self.edge_importance = [1] * len(self.st_gcn_networks)

        if num_class is not None:
            self.cls = nn.Conv2d(256, num_class, kernel_size=1)
        else:
            self.cls = lambda x: x  # identity, no parameters

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Per-channel data normalization across joints.
        N, C, T, V = x.size()
        x = x.permute(0, 3, 1, 2).contiguous()         # (N, V, C, T)
        x = x.view(N, V * C, T)
        x = self.data_bn(x)
        x = x.view(N, V, C, T)
        x = x.permute(0, 2, 3, 1).contiguous()         # (N, C, T, V)

        for gcn, importance in zip(self.st_gcn_networks, self.edge_importance):
            x = gcn(x, self.A * importance)

        x = F.avg_pool2d(x, x.size()[2:])
        x = self.cls(x)
        return x.view(x.size(0), -1)


class TwoStreamSpatialTemporalGraph(nn.Module):
    """Two-stream ST-GCN classifier (points stream + motion stream).

    Input is a tuple ``(pts, mot)``:

    * ``pts``: ``(N, 3, T, V)`` - x, y, score per joint per frame.
    * ``mot``: ``(N, 2, T-1, V)`` - temporal differences of (x, y).

    Output: ``(N, num_class)`` sigmoid-activated multi-label logits.
    """

    def __init__(self,
                 graph_args: dict,
                 num_class: int,
                 edge_importance_weighting: bool = True,
                 **kwargs) -> None:
        super().__init__()
        self.pts_stream = StreamSpatialTemporalGraph(
            3, graph_args, None, edge_importance_weighting, **kwargs)
        self.mot_stream = StreamSpatialTemporalGraph(
            2, graph_args, None, edge_importance_weighting, **kwargs)
        self.fcn = nn.Linear(256 * 2, num_class)

    def forward(self,
                inputs: Tuple[torch.Tensor, torch.Tensor]) -> torch.Tensor:
        out_pts = self.pts_stream(inputs[0])
        out_mot = self.mot_stream(inputs[1])
        concat = torch.cat([out_pts, out_mot], dim=-1)
        out = self.fcn(concat)
        return torch.sigmoid(out)


__all__ = [
    "GraphConvolution",
    "StGcnBlock",
    "StreamSpatialTemporalGraph",
    "TwoStreamSpatialTemporalGraph",
]
