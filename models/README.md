# Released models

Trained-policy **bytes** ship as **GitHub Release assets** (kept out of git
history); each release's **provenance** is committed here so a checkout tells
you what exists, its stats, its exact `sha256`, and how to fetch it.

Layout — one directory per release:

```
models/<release-name>/
  MANIFEST.json    # episodes, win rates, config, hyperparameters,
                   #   trained-with git SHA, lib versions, asset sha256, tag
  metrics.jsonl    # full training curve behind the run's dashboard
```

The `model.zip` itself is **not** in the tree. Fetch it from the Release:

```bash
gh release download <release-name> -p model.zip -D models/<release-name>
```

Evaluate or resume from a fetched model:

```bash
# Deterministic win rate (P reaching the Antechamber):
blueprince-train --evaluate 2000 --model models/<release-name>/model.zip

# Resume/experiment from it: seed a fresh run dir, then train continues from it
mkdir -p runs/experiment
cp models/<release-name>/model.zip runs/experiment/latest.zip
blueprince-train --checkpoint-dir runs/experiment          # reward changes OK
```

Reward changes warm-start cleanly from a released model; changing the
observation (`env/obs.py`) or action space (`env/actions.py`) changes the
network shape and requires training from scratch.

## Cutting a new release

`tools/make_release.py` is the single source of truth — it writes the manifest
with the model's `sha256`, and on `--publish` creates the tag + Release with
those exact bytes and verifies the upload round-trips:

```bash
python tools/make_release.py \
    --checkpoint-dir runs/<name> --name <release-name> --tag <release-name> \
    --trained-with-sha $(git rev-parse HEAD) --metrics runs/metrics.jsonl \
    --eval-episodes 2000 --eval-p <p> --eval-ci <lo> <hi> --eval-rank <rank> \
    --publish
```

Run `--publish` on the merged default branch so the tag points at the commit
that carries the manifest.
