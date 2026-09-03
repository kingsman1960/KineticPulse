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
| `kaggle fall detection` | Secondary 3 | 374 | train only | `Fall Detected`, `Walking`, `Sitting` | Kaggle (see below) |
| `le2i fall detection` | Secondary 4 | 1,211 | train only | `fallen`, `falling`, `stand` (generated) | Le2i / ImViA, cite Charfi et al. |

- Primary contributes **all** of `train`, `valid`, `test`.
- Secondaries only contribute to `train` (they have no validation/test splits, and we never want to evaluate against a different annotation style than we train against).
- Primary's `valid/` (266) and `test/` (100) are **never touched** by the merge — evaluation stays honest.

Secondaries 3 and 4 were added to close the two measured gaps in the v2
checkpoint: `sitting` had a single source, and `falling` val recall sat at
~0.69 for want of mid-fall frames. Both are produced by a prepare script
rather than being dropped in as-is — see [Extra sources](#extra-sources).

## Remap policy

| Source class | -> | Unified | Notes |
|---|---|---|---|
| `stand` / `standing` | -> | `stand` | Direct, semantically identical |
| `falling` | -> | `falling` | Direct |
| `fallen` | -> | `fallen` | Direct |
| `fall_down` (Sec. 2) | -> | `fallen` | Spot-check recommended — see below |
| `sitting` (Sec. 2) | -> | `sitting` | First-class posture in v2. See [Sitting label-noise caveat](#sitting-label-noise-caveat). |
| `bending` (Sec. 1) | -> | **DROP** | Removed because Primary has no bending class and we don't want the model penalising bending postures as detections it has to invent a class for. Image is dropped along with the label. |
| `Fall Detected` (Sec. 3) | -> | `fallen` | Same spot-check caveat as `fall_down`. Kept rather than dropped: these images mix classes, and dropping the box would leave a labelled person as unlabelled background. |
| `Walking` (Sec. 3) | -> | `stand` | Upright and in motion. |
| `Sitting` (Sec. 3) | -> | `sitting` | Second `sitting` source. |
| Sec. 4 (all) | -> | identity | `prepare_le2i.py` already emits unified indices. |
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

## Extra sources

Both of these need a prepare step before `merge_datasets.py` can see them.

### Secondary 3 — Kaggle (`sitting`)

[uttejkumarkandagatla/fall-detection-dataset](https://www.kaggle.com/datasets/uttejkumarkandagatla/fall-detection-dataset). Download the zip, then:

```bash
python scripts/prepare_kaggle_fall.py "dataset/archive (1).zip"
```

Ships `fall_dataset/{images,labels}/{train,val}`; the script rewrites that into
`dataset/kaggle fall detection/train/{images,labels}`. Only `train` is taken —
all 111 `val` stems also appear in `train`, so that split is redundant.

### Secondary 4 — Le2i / ImViA (`falling`)

[Fall Detection Dataset](https://search-data.ubfc.fr/imvia/FR-13002091000019-2024-04-09_Fall-Detection-Dataset.html) (`FallDataset.zip`, 8.95 GB):

```bash
curl -L -C - -o dataset/FallDataset.zip "https://search-data.ubfc.fr/imvia/dl_data.php?file=101"
python scripts/prepare_le2i.py dataset/FallDataset.zip --dry-run
python scripts/prepare_le2i.py dataset/FallDataset.zip
```

Le2i annotates the first and last frame of each fall plus a per-frame bounding
box, so `stand` / `falling` / `fallen` frames can be cut automatically. Two
things the script deliberately does **not** do:

- **The whole fall window is not `falling`.** Le2i's window runs until the body
  comes to rest; filmstrips of `Coffee_room_01` video (6) and video (19) show
  the subject already flat on the floor from ~60 % of the window and still
  upright at 0 %. Only 10–60 % is emitted (`--falling-lo` / `--falling-hi`);
  the ambiguous tail is dropped. Re-render a filmstrip if you retune these.
- **No-fall videos (`0`/`0`) are skipped entirely.** Their ADL content includes
  sitting down and lying on furniture — the same false-positive risk that makes
  us drop `lying_down` from Secondary 2.

`Office`, `Lecture_room` and `Coffee_room_02` ship no `Annotation_files` and are
skipped.

### Considered and rejected

- **TsetFall** — the only public set with `Falling` as a first-class label, but
  its Mega folder is empty as of 2026-09.
- **CAUCAFall** — home environment with YOLO labels, but Mendeley's public API
  exposes only the documentation files, and its labels are `fall` / `no-fall`
  only, so `falling` would need manual annotation anyway.
- **More Roboflow "fall / no-fall" sets** — same domain and same classes we
  already have; they add volume to the classes that are already strong.

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
│   ├── images/              # primary + all secondaries (dedup'd)
│   └── labels/
├── valid/
│   ├── images/              # primary only (no sitting examples - acceptable, see caveat)
│   └── labels/
└── test/
    ├── images/              # primary only
    └── labels/
```

The `valid/` and `test/` splits come from Primary alone and therefore contain **no `sitting` ground-truth labels**. Per-class metrics for `sitting` will be unavailable until a secondary ships a validation split or you manually curate seated examples from Primary into a held-out set. `sitting` is trained on Secondary 2 + 3 only and validated implicitly through `stand` recall (no drop) and runtime spot-checks.

Because valid/test are untouched, the `falling` boost from Secondary 4 is
measurable the honest way: re-run `scripts/eval.py --split val` and compare
per-class `falling` recall against the 0.69 baseline.

Image filenames are prefixed (`p1__`, `s1__`, `s2__`, `s3__`, `s4__`) to avoid collisions and to make per-dataset filtering trivial later.

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
- **Secondary 3** follows the uploader's terms on Kaggle.
- **Secondary 4** (Le2i / ImViA) is research-use with the Charfi et al. citation below; the extracted frames are derived work, so do not redistribute them either.

For now, the entire `dataset/` directory is in `.gitignore` to keep the repository small and avoid accidentally publishing private data.

## Obtaining the data

The raw datasets are not stored in git. To reproduce the training data:

1. Download each dataset from its source (Roboflow Universe / Roboflow workspace) as a YOLOv8 export.
2. Extract each into this `dataset/` folder, keeping the folder names exactly as listed above (case and spacing matter — the merge script looks them up by name).
3. For Secondaries 3 and 4, run the prepare scripts in [Extra sources](#extra-sources) instead — they generate the folder for you.
4. Run `python scripts/merge_datasets.py`.

Source URLs:

- Primary: <https://universe.roboflow.com/robo-vobcs/fall-detection-stqne/dataset/1>
- Secondary 1: Roboflow workspace `youngwon-cho-develop` (Fall Detection)
- Secondary 2: Roboflow workspace `youngwon-cho-develop` (fallen detection)
- Secondary 3: <https://www.kaggle.com/datasets/uttejkumarkandagatla/fall-detection-dataset>
- Secondary 4: <https://search-data.ubfc.fr/imvia/FR-13002091000019-2024-04-09_Fall-Detection-Dataset.html>

Le2i requires the citation in its `README.txt`: I. Charfi, J. Mitéran,
J. Dubois, M. Atri, R. Tourki, *"Optimised spatio-temporal descriptors for
real-time fall detection: comparison of SVM and Adaboost based
classification"*, Journal of Electronic Imaging 22(4), 2013.
