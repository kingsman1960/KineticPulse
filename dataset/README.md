# KineticPulse Datasets

This folder contains the training data for the KineticPulse fall-detection model. The raw datasets and the generated `_merged/` output are **gitignored** — see [Obtaining the data](#obtaining-the-data) below.

## Unified schema

All three source datasets are remapped to a single, simple 3-class schema:

| Index | Class | Meaning |
|---:|---|---|
| 0 | `fallen` | Subject on the ground (post-fall, lying / collapsed) |
| 1 | `falling` | Subject mid-fall (in-progress transition) |
| 2 | `stand` | Subject upright / standing |

This is **"safe Option A"** — small label space, easy to evaluate, sized to match the original primary dataset.

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
| `bending` (Sec. 1) | -> | **DROP** | Removed because Primary has no bending class and we don't want the model penalising bending postures as detections it has to invent a class for. Image is dropped along with the label. |
| `lying_down` (Sec. 2) | -> | **DROP** | Too ambiguous — `lying_down` includes people on beds/couches/yoga mats, not just floor falls. Mapping these to `fallen` would teach the model that anyone reclining is in distress, which is exactly the false-positive class PRD §5.4 exists to suppress. |
| `sitting` (Sec. 2) | -> | **DROP** | Primary has no sitting class; safer to drop than to fold into `stand`. |

When all labels for an image are dropped, **both** the label file and the image are removed from the merged output (never keep an "empty" image — YOLO would treat it as a negative and learn to suppress legitimate detections of those postures).

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
├── data.yaml                # nc: 3, names: ['fallen', 'falling', 'stand']
├── train/
│   ├── images/              # primary + secondary 1 + secondary 2 (dedup'd)
│   └── labels/
├── valid/
│   ├── images/              # primary only
│   └── labels/
└── test/
    ├── images/              # primary only
    └── labels/
```

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
