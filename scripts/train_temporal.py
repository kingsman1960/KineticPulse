"""Fine-tune the TSSTG (two-stream ST-GCN) action classifier.

This is the supervised counterpart to ``extract_keypoints.py`` /
``live_predict.py --record``: it reads the labelled ``.npz`` clips
those tools produce and continues training the released ``tsstg-model.pth``
checkpoint on **your** camera viewpoints.

Why fine-tune at all?
=====================

The released GajuuzZ checkpoint was trained on Le2i fall scenes and
generalises remarkably well, but the ``sitting <-> falling`` border
oscillates on novel angles (e.g. a laptop webcam tilted up at the
subject - which is exactly our deployment). A few hundred labelled
clips of *our* room, *our* camera, *our* people is enough to lock that
border down without losing any of the upstream generalisation.

How is the network shaped?
==========================

The model keeps its **7-output** head (``Standing, Walking, Sitting,
Lying Down, Stand up, Sit down, Fall Down``) so the upstream weights
load with ``strict=True``. We supervise only the four classes we
record (``stand / sitting / fallen / falling``), each mapped to its
canonical 7-way index:

* ``stand    -> Standing  (0)``
* ``sitting  -> Sitting   (2)``
* ``fallen   -> Lying Down(3)``
* ``falling  -> Fall Down (6)``

Loss is BCE on the sigmoided 7-way output: targets are one-hot at the
mapped index and 0 everywhere else. The four "transition" classes the
upstream network already learnt (``Walking``, ``Stand up``, ``Sit down``)
are simply unsupervised and their existing weights drift slowly.

Inputs
======

::

    dataset/temporal_clips/
      fallen/   *.npz
      falling/  *.npz
      stand/    *.npz
      sitting/  *.npz

Each ``.npz`` contains ``keypoints (T, 17, 3)``, ``label``, ``fps``,
``image_size``, ``video_path`` (see ``extract_keypoints.py`` for the
exact schema).

Output
======

::

    models/tsstg/finetune-<run-name>/
      best.pth      # lowest val loss
      last.pth      # last epoch
      train.csv     # per-epoch metrics
      args.json     # frozen CLI snapshot
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Mapping from our 4-class schema to the 7-way head index.
LABEL_TO_TSSTG_IDX = {
    "stand":   0,   # Standing
    "sitting": 2,   # Sitting
    "fallen":  3,   # Lying Down
    "falling": 6,   # Fall Down
}
TSSTG_NUM_CLASSES = 7
VALID_LABELS = tuple(LABEL_TO_TSSTG_IDX.keys())


# --------------------------------------------------------------------------- #
# Dataset
# --------------------------------------------------------------------------- #


@dataclass
class ClipMeta:
    path: Path
    label: str
    label_idx_4cls: int           # 0..3 in our schema (for stratified split)
    label_idx_tsstg: int          # 0..6 in the TSSTG head
    n_frames: int
    image_size: Tuple[int, int]   # (W, H)


def discover_clips(root: Path) -> List[ClipMeta]:
    """Walk ``<root>/<label>/*.npz`` and return one ``ClipMeta`` per file.

    Clips whose folder-name and stored-label disagree are flagged but
    still loaded (folder name wins, with a warning).
    """
    metas: List[ClipMeta] = []
    if not root.exists():
        raise FileNotFoundError(f"clips directory not found: {root}")

    for label_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        label = label_dir.name.lower()
        if label not in VALID_LABELS:
            print(f"[skip] '{label_dir.name}' is not in {VALID_LABELS}.")
            continue
        for npz in sorted(label_dir.glob("*.npz")):
            try:
                with np.load(npz, allow_pickle=False) as f:
                    kpts = f["keypoints"]
                    inner_label = str(f["label"])
                    img_size = tuple(int(v) for v in f["image_size"])
            except Exception as exc:
                print(f"[skip] could not read {npz}: {exc}")
                continue
            if inner_label.lower() != label:
                print(f"[warn] {npz.name}: folder='{label}' "
                      f"but payload label='{inner_label}'. Folder wins.")
            if kpts.ndim != 3 or kpts.shape[1:] != (17, 3):
                print(f"[skip] {npz}: unexpected keypoint shape {kpts.shape}")
                continue
            metas.append(ClipMeta(
                path=npz,
                label=label,
                label_idx_4cls=VALID_LABELS.index(label),
                label_idx_tsstg=LABEL_TO_TSSTG_IDX[label],
                n_frames=kpts.shape[0],
                image_size=(img_size[0], img_size[1]),
            ))
    return metas


def stratified_split(metas: List[ClipMeta], val_frac: float, seed: int
                     ) -> Tuple[List[ClipMeta], List[ClipMeta]]:
    """Per-class train/val split so every class appears in val."""
    rng = random.Random(seed)
    train: List[ClipMeta] = []
    val: List[ClipMeta] = []
    by_lbl: dict = {}
    for m in metas:
        by_lbl.setdefault(m.label, []).append(m)
    for lbl, items in by_lbl.items():
        rng.shuffle(items)
        n_val = max(1, int(round(len(items) * val_frac))) if len(items) > 1 else 0
        val.extend(items[:n_val])
        train.extend(items[n_val:])
    return train, val


def _normalise_clip(clip17_xyc: np.ndarray, image_size: Tuple[int, int]
                    ) -> np.ndarray:
    """COCO-17 (T, 17, 3) -> coco_cut (T, 14, 3) in [-1, 1] xy + raw score.

    Mirrors ``TsstgClassifier.predict`` so train and inference see the
    same input distribution. Done in numpy because torch.fft is not
    needed and numpy is the existing convention in our temporal module.
    """
    from kineticpulse.temporal.keypoint_adapter import coco17_to_coco_cut_14
    from kineticpulse.temporal.tsstg import (
        _normalize_points_with_size, _scale_pose,
    )

    pts = coco17_to_coco_cut_14(clip17_xyc)            # (T, 14, 3)
    w, h = int(image_size[0]), int(image_size[1])
    pts[..., :2] = _normalize_points_with_size(pts[..., :2], w, h)
    pts[..., :2] = _scale_pose(pts[..., :2])
    return pts.astype(np.float32, copy=False)


def _load_window(meta: ClipMeta, window: int, *, training: bool,
                 rng: random.Random) -> Optional[np.ndarray]:
    """Load one (window, 17, 3) sub-clip from disk.

    * If the source is longer than ``window``: random crop in training,
      centre crop at eval.
    * If shorter: tail-pad with the last frame so the model still sees a
      full-length window.
    * Returns ``None`` if the clip has fewer than 2 frames with any
      keypoint score (i.e. the pose model failed throughout) so the
      motion stream cannot be computed.
    """
    with np.load(meta.path, allow_pickle=False) as f:
        kpts = f["keypoints"]                    # (T, 17, 3)
        kpts = kpts.astype(np.float32, copy=True)

    if kpts.shape[0] < 2:
        return None
    # Forward-fill zero-score rows so blank frames don't poison normalisation.
    last_good = None
    for i in range(kpts.shape[0]):
        if kpts[i, :, 2].sum() <= 1e-6:
            if last_good is None:
                continue
            kpts[i] = last_good
        else:
            last_good = kpts[i].copy()

    T = kpts.shape[0]
    if T >= window:
        if training:
            start = rng.randint(0, T - window)
        else:
            start = (T - window) // 2
        sub = kpts[start:start + window]
    else:
        pad = np.repeat(kpts[-1:], window - T, axis=0)
        sub = np.concatenate([kpts, pad], axis=0)
    return sub


def collate_clips(samples: List[Tuple[np.ndarray, int]],
                  ) -> Tuple["torch.Tensor", "torch.Tensor", "torch.Tensor"]:
    """List of (clip(T,V,3), tsstg_idx) -> (pts, mot, target7) batched."""
    import torch

    pts_list = []
    mot_list = []
    tgt_list = []
    for clip_xyc, tsstg_idx in samples:
        # (T, V, C) -> (C, T, V)
        pts = torch.from_numpy(clip_xyc).float().permute(2, 0, 1)
        mot = pts[:2, 1:, :] - pts[:2, :-1, :]
        target = torch.zeros(TSSTG_NUM_CLASSES, dtype=torch.float32)
        target[tsstg_idx] = 1.0
        pts_list.append(pts)
        mot_list.append(mot)
        tgt_list.append(target)
    return (torch.stack(pts_list), torch.stack(mot_list), torch.stack(tgt_list))


# --------------------------------------------------------------------------- #
# Train / evaluate
# --------------------------------------------------------------------------- #


def run_one_epoch(model, loader, *, device, optimizer=None, criterion):
    """Returns ``(avg_loss, top1_acc_4cls)`` for the given loader."""
    import torch

    is_train = optimizer is not None
    model.train(is_train)
    total_loss = 0.0
    n = 0
    correct = 0
    confusion = np.zeros((4, 4), dtype=np.int64)

    for pts, mot, target in loader:
        pts = pts.to(device, non_blocking=True)
        mot = mot.to(device, non_blocking=True)
        target = target.to(device, non_blocking=True)

        if is_train:
            optimizer.zero_grad()

        with torch.set_grad_enabled(is_train):
            out = model((pts, mot))                # already sigmoid
            # Numerical safety for BCELoss: clip away from {0, 1}.
            out_clamped = torch.clamp(out, 1e-7, 1.0 - 1e-7)
            loss = criterion(out_clamped, target)

        if is_train:
            loss.backward()
            optimizer.step()

        bs = pts.size(0)
        total_loss += float(loss.item()) * bs
        n += bs

        # 4-class accuracy: compare argmax over the 4 indices we care about.
        with torch.no_grad():
            sup_idx = list(LABEL_TO_TSSTG_IDX.values())
            sup_logits = out[:, sup_idx]           # (B, 4)
            pred = sup_logits.argmax(dim=1)        # 0..3
            true = target[:, sup_idx].argmax(dim=1)
            correct += int((pred == true).sum().item())
            for p, t in zip(pred.cpu().numpy(), true.cpu().numpy()):
                confusion[t, p] += 1

    avg_loss = total_loss / max(1, n)
    acc = correct / max(1, n)
    return avg_loss, acc, confusion


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__.split("\n\n", 1)[0],
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--clips", type=Path,
                   default=REPO_ROOT / "dataset" / "temporal_clips",
                   help="Folder of <label>/*.npz clips (record + extract output).")
    p.add_argument("--init-weights", type=Path,
                   default=REPO_ROOT / "models" / "tsstg" / "tsstg-model.pth",
                   help="Upstream TSSTG checkpoint to start from.")
    p.add_argument("--out-root", type=Path,
                   default=REPO_ROOT / "models" / "tsstg",
                   help="Where to create the per-run output directory.")
    p.add_argument("--run-name", type=str, default=None,
                   help="Sub-folder under --out-root. Default: ts-finetune-<timestamp>.")
    p.add_argument("--window", type=int, default=30,
                   help="Frames per training clip (matches inference).")
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--lr", type=float, default=1e-4,
                   help="Adam LR. Keep small - this is fine-tuning.")
    p.add_argument("--weight-decay", type=float, default=1e-4)
    p.add_argument("--val-frac", type=float, default=0.2)
    p.add_argument("--samples-per-clip", type=int, default=4,
                   help="Random crops per clip per epoch (training only).")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--device", type=str, default="auto",
                   help='"auto" | "cuda" | "cuda:0" | "cpu"')
    p.add_argument("--num-workers", type=int, default=0,
                   help="DataLoader workers. 0 is safest on Windows.")
    p.add_argument("--freeze-backbone", action="store_true",
                   help="Train only the final fcn linear layer "
                        "(fastest + least overfitting on small datasets).")
    return p.parse_args()


def _resolve_device(spec: str):
    import torch
    if spec in ("auto", ""):
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(spec)


def main() -> int:
    args = parse_args()

    try:
        import torch
        from torch.utils.data import DataLoader, Dataset
        import torch.nn as nn
    except ImportError:
        print("[error] PyTorch is required. See requirements.txt.",
              file=sys.stderr)
        return 2

    from kineticpulse.temporal.stgcn_model import TwoStreamSpatialTemporalGraph

    rng_master = random.Random(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    metas = discover_clips(args.clips)
    if not metas:
        print(f"[error] no clips found under {args.clips}", file=sys.stderr)
        return 1
    by_lbl: dict = {}
    for m in metas:
        by_lbl[m.label] = by_lbl.get(m.label, 0) + 1
    print(f"Discovered {len(metas)} clips across {len(by_lbl)} labels:")
    for lbl in VALID_LABELS:
        print(f"  {lbl:<8s}  {by_lbl.get(lbl, 0):4d}")
    missing = [l for l in VALID_LABELS if by_lbl.get(l, 0) == 0]
    if missing:
        print(f"[warn] no clips for: {missing} - training will skew "
              "toward classes that *are* present.")

    train_meta, val_meta = stratified_split(metas, args.val_frac, args.seed)
    print(f"split: train={len(train_meta)}  val={len(val_meta)}")

    # ---------- datasets / loaders ----------
    class ClipDataset(Dataset):
        def __init__(self, ms: List[ClipMeta], *, training: bool,
                     samples_per_clip: int, window: int, seed: int):
            self.ms = ms
            self.training = training
            self.samples_per_clip = samples_per_clip if training else 1
            self.window = window
            self.rng = random.Random(seed)

        def __len__(self):
            return len(self.ms) * self.samples_per_clip

        def __getitem__(self, idx):
            meta = self.ms[idx % len(self.ms)]
            sub = _load_window(meta, self.window, training=self.training,
                               rng=self.rng)
            if sub is None:
                # Replace with the next clip; tiny edge case.
                meta = self.ms[(idx + 1) % len(self.ms)]
                sub = _load_window(meta, self.window, training=False, rng=self.rng)
            normed = _normalise_clip(sub, meta.image_size)
            return normed, meta.label_idx_tsstg

    train_ds = ClipDataset(train_meta, training=True,
                           samples_per_clip=args.samples_per_clip,
                           window=args.window, seed=args.seed)
    val_ds = ClipDataset(val_meta or train_meta[:1], training=False,
                         samples_per_clip=1,
                         window=args.window, seed=args.seed + 1)

    def _collate(batch):
        return collate_clips(batch)

    train_loader = DataLoader(train_ds, batch_size=args.batch_size,
                              shuffle=True, num_workers=args.num_workers,
                              collate_fn=_collate, drop_last=False)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size,
                            shuffle=False, num_workers=args.num_workers,
                            collate_fn=_collate, drop_last=False)

    # ---------- model ----------
    device = _resolve_device(args.device)
    model = TwoStreamSpatialTemporalGraph(
        graph_args={"strategy": "spatial", "layout": "coco_cut"},
        num_class=TSSTG_NUM_CLASSES,
    ).to(device)

    if args.init_weights and args.init_weights.exists():
        print(f"Initialising from {args.init_weights}")
        state = torch.load(str(args.init_weights), map_location=device,
                           weights_only=False)
        model.load_state_dict(state, strict=True)
    else:
        print(f"[warn] init weights not found at {args.init_weights}; "
              "training from scratch.")

    if args.freeze_backbone:
        for name, p_ in model.named_parameters():
            if not name.startswith("fcn"):
                p_.requires_grad = False
        trainable = [p for p in model.parameters() if p.requires_grad]
        print(f"frozen backbone: trainable params={sum(p.numel() for p in trainable):,}")
    else:
        trainable = list(model.parameters())

    optimizer = torch.optim.Adam(trainable, lr=args.lr,
                                 weight_decay=args.weight_decay)
    criterion = nn.BCELoss()

    # ---------- output dir ----------
    run_name = args.run_name or f"finetune-{time.strftime('%Y%m%d-%H%M%S')}"
    run_dir = args.out_root / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "args.json").write_text(
        json.dumps({k: (str(v) if isinstance(v, Path) else v)
                    for k, v in vars(args).items()}, indent=2),
        encoding="utf-8",
    )

    # ---------- training loop ----------
    csv_path = run_dir / "train.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        writer.writerow(["epoch", "train_loss", "train_acc4", "val_loss", "val_acc4"])
        best_val = math.inf
        for epoch in range(1, args.epochs + 1):
            t0 = time.monotonic()
            tr_loss, tr_acc, _ = run_one_epoch(
                model, train_loader, device=device,
                optimizer=optimizer, criterion=criterion,
            )
            va_loss, va_acc, va_conf = run_one_epoch(
                model, val_loader, device=device,
                optimizer=None, criterion=criterion,
            )
            dt = time.monotonic() - t0
            print(f"epoch {epoch:3d}/{args.epochs}  "
                  f"train_loss={tr_loss:.4f} acc4={tr_acc:.3f}  "
                  f"val_loss={va_loss:.4f} acc4={va_acc:.3f}  "
                  f"({dt:.1f}s)")
            writer.writerow([epoch, f"{tr_loss:.6f}", f"{tr_acc:.4f}",
                             f"{va_loss:.6f}", f"{va_acc:.4f}"])
            fp.flush()

            if va_loss < best_val:
                best_val = va_loss
                best_path = run_dir / "best.pth"
                torch.save(model.state_dict(), best_path)
                print(f"  -> new best val loss; saved {best_path.name}")

            torch.save(model.state_dict(), run_dir / "last.pth")

    # ---------- final eval ----------
    _, final_acc, conf = run_one_epoch(
        model, val_loader, device=device, optimizer=None, criterion=criterion,
    )
    print("Final val 4-class confusion (rows=true, cols=pred):")
    print("           " + "  ".join(f"{l:<8s}" for l in VALID_LABELS))
    for i, lbl in enumerate(VALID_LABELS):
        row = "  ".join(f"{conf[i, j]:<8d}" for j in range(4))
        print(f"  {lbl:<8s} {row}")
    print(f"Final val 4-class accuracy: {final_acc:.3f}")
    print(f"\nArtifacts: {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
