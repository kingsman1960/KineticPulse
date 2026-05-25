# KineticPulse Datasets

This folder contains the training data for the KineticPulse fall-detection model. The raw datasets and the generated `_merged/` output are **gitignored** — see [Obtaining the data](#obtaining-the-data) below.

## Unified schema

All three source datasets are remapped to a single 4-class schema:

| Index | Class | Meaning |
|---:|---|---|
| 0 | `fallen` | Subject on the ground (post-fall, lying / collapsed) |
| 1 | `falling` | Subject mid-fall (in-progress transition) |
| 2 | `stand` | Subject upright / standing |
| 3 | `sitting` | Subject seated (chair, floor, edge of bed) |

`sitting` was added in v2 to give the fusion engine a distinct non-fall posture to dismiss (rather than asking the engine to infer "seated" from `stand` + torso angle). The class order is **append-only** so previously trained checkpoints can be rolled forward without re-labelling.

## Source datasets

| Folder | Role | Images | Splits | Classes (source) | License |
|---|---|---|---|---|---|
| `fall detection.v1i.yolov8` | **Primary** | 1,652 (1286 / 266 / 100) | train + valid + test | `fallen`, `falling`, `stand` | CC BY 4.0 |
| `Fall Detection.yolov8` | Secondary 1 | 910 | train only | `bending`, `fallen`, `falling`, `standing` | Private |
| `fallen detection.yolov8` | Secondary 2 | 500 | train only | `fall_down`, `lying_down`, `sitting`, `standing` | Private |

- Primary contributes **all** of `train`, `valid`, `test`.
- Secondaries only contribute to `train` (they have no validation/test splits, and we never want to evaluate against a different annotation style than we train against).
- Primary's `valid/` (266) and `test/` (100) are **never touched** by the merge — evaluation stays honest.

## Remap policy

| Source class | -> | Unified | Notes |
|---|---|---|---|
| `stand` / `standing` | -> | `stand` | Direct, semantically identical |
| `falling` | -> | `falling` | Direct |
| `fallen` | -> | `fallen` | Direct |
| `fall_down` (Sec. 2) | -> | `fallen` | Spot-check recommended — see below |
| `sitting` (Sec. 2) | -> | `sitting` | First-class posture in v2. See [Sitting label-noise caveat](#sitting-label-noise-caveat). |
| `bending` (Sec. 1) | -> | **DROP** | Removed because Primary has no bending class and we don't want the model penalising bending postures as detections it has to invent a class for. Image is dropped along with the label. |
| `lying_down` (Sec. 2) | -> | **DROP** | Too ambiguous — `lying_down` includes people on beds/couches/yoga mats, not just floor falls. Mapping these to `fallen` would teach the model that anyone reclining is in distress, which is exactly the false-positive class PRD §5.4 exists to suppress. |

When all labels for an image are dropped, **both** the label file and the image are removed from the merged output (never keep an "empty" image — YOLO would treat it as a negative and learn to suppress legitimate detections of those postures).

### Sitting label-noise caveat

Only **Secondary 2** explicitly labels seated subjects. The Primary and Secondary 1 datasets have no `sitting` class, so any seated person in those datasets stays labelled as `stand`. The merged training set therefore contains a small population of seated people with the wrong class.

We accept this for v2 because:

- Primary is overwhelmingly walking / falling subjects framed in motion — seated people are a small fraction of the `stand` class.
- The fusion layer's pose features (`torso_angle_deg`, `aspect_ratio`, `centroid_vel_pps`) already discriminate seated from standing postures, so even when the detector confuses `stand` and `sitting`, the downstream `pose_signature()` reaches the same `UPRIGHT` summary and the runtime still dismisses the false positive (Scenario D).

If post-training evaluation shows heavy `stand` <-> `sitting` confusion (>5 % per-class confusion in the `valid/` split), the audit path is:

1. Run `python scripts/eval.py --weights runs/detect/<run>/weights/best.pt` and inspect the confusion matrix.
2. Filter the merged training set for primary-source `stand` labels (filenames prefixed `p1__`) and spot-check them. Relabel obvious seated examples to `sitting`.
3. Re-run `scripts/merge_datasets.py` and retrain.

### `fall_down` spot-check note

`fall_down` is ambiguous in English. In Secondary 2 the other three classes (`lying_down`, `sitting`, `standing`) are all **postural states**, so `fall_down` is almost certainly intended as the resulting state ("fallen on the ground") rather than the in-progress action. We default it to `fallen`.

The merge script prints 20 sample file paths from this class on every run. Open a few:

- If the subject is **on the ground**, the default mapping (`fall_down -> fallen`) is correct.
- If the subject is **mid-air / mid-collapse**, edit `scripts/merge_datasets.py` and change `REMAPS["fallen detection.yolov8"][0]` from `"fallen"` to `"falling"`, then re-run.

## Generating the merged dataset

From the repository root:

```bash
# Optional but recommended: enables dHash near-duplicate removal on the train set
pip install pillow

# Dry-run: shows what would happen, prints all stats, no writes
python scripts/merge_datasets.py --dry-run

# Real run: writes dataset/_merged/
python scripts/merge_datasets.py
```

Output layout:

```
dataset/_merged/
├── data.yaml                # nc: 4, names: ['fallen', 'falling', 'stand', 'sitting']
├── train/
│   ├── images/              # primary + secondary 1 + secondary 2 (dedup'd)
│   └── labels/
├── valid/
│   ├── images/              # primary only (no sitting examples - acceptable, see caveat)
│   └── labels/
└── test/
    ├── images/              # primary only
    └── labels/
```

The `valid/` and `test/` splits come from Primary alone and therefore contain **no `sitting` ground-truth labels**. Per-class metrics for `sitting` will be unavailable until either Secondary 2 ships a validation split or you manually curate seated examples from Primary into a held-out set. For the v2 model the `sitting` class is trained on Secondary 2 train only and validated implicitly through `stand` recall (no drop) and runtime spot-checks.

Image filenames are prefixed (`p1__`, `s1__`, `s2__`) to avoid collisions and to make per-dataset filtering trivial later.

### What the script does

1. Reads each source `data.yaml` and applies the remap table in the script.
2. Rewrites every YOLO label file with new class indices and drops mapped-to-DROP lines.
3. If an image has zero surviving labels, both the image and the label file are skipped.
4. Optionally runs **dHash perceptual deduplication across the merged `train/` split only** (valid/test untouched), to catch cases where the two same-workspace secondary datasets share source images.
5. Prints a full report: images seen / kept / dropped, duplicate count, label remap / drop counts, per-class counts, per-split counts, per-dataset contribution, and the `fall_down` spot-check sample.
6. Writes a unified `data.yaml`.

## Licenses & redistribution

- **Primary** is CC BY 4.0 — redistributable with attribution.
- **Secondary 1** and **Secondary 2** are marked **Private** on Roboflow (workspace: `youngwon-cho-develop`).
  - If you own that workspace, no action needed — confirm and update this note.
  - If you do not, you may train on these datasets locally, but **do not** redistribute the images, labels, or this merged folder.

For now, the entire `dataset/` directory is in `.gitignore` to keep the repository small and avoid accidentally publishing private data.

## Obtaining the data

The raw datasets are not stored in git. To reproduce the training data:

1. Download each dataset from its source (Roboflow Universe / Roboflow workspace) as a YOLOv8 export.
2. Extract each into this `dataset/` folder, keeping the folder names exactly as listed above (case and spacing matter — the merge script looks them up by name).
3. Run `python scripts/merge_datasets.py`.

Source URLs:

- Primary: <https://universe.roboflow.com/robo-vobcs/fall-detection-stqne/dataset/1>
- Secondary 1: Roboflow workspace `youngwon-cho-develop` (Fall Detection)
- Secondary 2: Roboflow workspace `youngwon-cho-develop` (fallen detection)
