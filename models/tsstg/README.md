# TSSTG action-classifier weights

The temporal action classifier (`kineticpulse.temporal.tsstg.TsstgClassifier`)
loads its weights from this folder. The default path baked into
`kineticpulse.config.TemporalConfig` and `config.example.yaml` is:

```
models/tsstg/tsstg-model.pth
```

These weights are **not redistributed** with the KineticPulse repository
because the source author publishes them on Google Drive only. Until they
are placed here, `TemporalHead` falls back to a deterministic
posture-feature heuristic (a single warning is logged on the first
prediction) and the rest of the pipeline keeps running.

## Download

> **Heads up (2024-): the original GajuuzZ Drive link is dead.** The upstream
> README still points at
> `https://drive.google.com/file/d/1mQQ4JHe58ylKbBqTjuKzpwN2nwKOWJ9u/...`,
> but the file has been removed by the author. Use the community mirror
> below instead. (See upstream issues
> [#99](https://github.com/GajuuzZ/Human-Falling-Detect-Tracks/issues/99)
> and [#109](https://github.com/GajuuzZ/Human-Falling-Detect-Tracks/issues/109).)

### Option A — automated (recommended)

```powershell
pip install gdown
python -m gdown --folder `
    "https://drive.google.com/drive/folders/1lrTI56k9QiIfMJhG9kzNjBzJh98KCIIO" `
    -O models/tsstg/_mirror
Move-Item models/tsstg/_mirror/TSSTG/tsstg-model.pth models/tsstg/tsstg-model.pth -Force
```

The mirror folder also contains weights for AlphaPose / Tiny-YOLO that
KineticPulse does not use; you can delete `models/tsstg/_mirror/` once the
move is done.

### Option B — manual

1. Open the community mirror folder:
   <https://drive.google.com/drive/folders/1lrTI56k9QiIfMJhG9kzNjBzJh98KCIIO>
   (shared by `@sankamohotttala` in upstream issue #99).
2. Inside `TSSTG/`, download `tsstg-model.pth` (≈24 MB).
3. Save it under this directory:

   ```
   KineticPulse/
       models/
           tsstg/
               tsstg-model.pth   <-- put it here
   ```

### Verify the checkpoint loads

```powershell
$env:KMP_DUPLICATE_LIB_OK='TRUE'
python -c "import numpy as np; from kineticpulse.temporal.tsstg import TsstgClassifier; c=TsstgClassifier(weights_path='models/tsstg/tsstg-model.pth', device='cuda'); p=c.predict(np.random.rand(30,17,3).astype('float32'), image_size=(640,480)); print('OK', p.argmax_label)"
```

On a Jetson Orin Nano Super or an RTX 4050 laptop you should see
`OK <label>` within a couple of seconds. The expected file size is
`24,708,522` bytes.

## What the checkpoint contains

* Two-Stream Spatial Temporal Graph CNN (`TwoStreamSpatialTemporalGraph`).
* Trained on the Le2i Fall Detection Dataset by the GajuuzZ project.
* Skeleton input format: `coco_cut` (14 joints, neck synthesised from
  shoulder midpoint).
* Output: 7-class sigmoid probabilities, in this order:
  `Standing, Walking, Sitting, Lying Down, Stand up, Sit down, Fall Down`.
  KineticPulse collapses these to its 4-class schema
  (`fallen, falling, stand, sitting`) inside
  `kineticpulse.temporal.tsstg.TsstgClassifier.predict`.

## Choosing a different checkpoint

If you fine-tune your own weights with the same architecture (same
`graph_args`, same `num_class=7`, same node ordering) you can drop them
in here under any filename and point `temporal.weights` in your
`config.yaml` at it. The model is intentionally byte-compatible with
the upstream so any TSSTG-style checkpoint loads with `strict=True`.
