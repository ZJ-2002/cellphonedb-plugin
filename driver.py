#!/usr/bin/env python3
"""Tier-1 driver for CellPhoneDB statistical analysis.

I/O translation only: reads engine-mounted inputs and env-rendered params,
calls the OFFICIAL cellphonedb API (pip-pinned in this image, digest pins both
code and the baked curated database), and leaves official output tables in
the artifact directory.
"""
import glob
import hashlib
import importlib.metadata
import inspect
import json
import os
import re
import sys


def env_str(name, default=None):
    raw = os.environ.get(name)
    return default if raw in (None, "") else raw


def env_bool(name, default):
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    # Explicit string parse — immune to the shell [ -n ] presence trap.
    return raw.strip().lower() in ("1", "true", "yes")


def env_typed(name, default, cast):
    raw = os.environ.get(name)
    return default if raw in (None, "") else cast(raw)


def main():
    counts = os.environ.get("AUTONOMICS_INPUT0") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not counts or not os.path.isfile(counts):
        sys.exit(f"driver: counts input missing or not a file: {counts!r}")
    # Outputs go to the workdir root so the manifest lists flat relative
    # paths (mtag/single-cell convention).
    out_dir = env_str("AUTONOMICS_WORKDIR", os.getcwd())

    meta = env_str("AUTONOMICS_INPUT1", "")
    cluster_col = env_str("CPDB_CLUSTER_COLUMN", "cluster")
    if not meta:
        # I/O translation: derive the official 2-column meta file from the
        # h5ad cell metadata instead of requiring the caller to materialize
        # it. Container-local scratch, not an artifact.
        import tempfile
        import anndata
        adata = anndata.read_h5ad(counts)
        if cluster_col not in adata.obs.columns:
            sys.exit(
                f"driver: cluster column {cluster_col!r} not in h5ad obs "
                f"(available: {sorted(map(str, adata.obs.columns))})"
            )
        meta = os.path.join(tempfile.mkdtemp(prefix="cpdb-"), "derived_meta.tsv")
        adata.obs[[cluster_col]].rename(columns={cluster_col: "cluster"}).to_csv(
            meta, sep="\t", index_label="Cell")

    zips = sorted(glob.glob(os.path.join(env_str("CPDB_ROOT", "/opt/cellphonedb"), "*.zip")))
    if len(zips) != 1:
        sys.exit(f"driver: expected exactly one baked database zip, found: {zips}")

    from cellphonedb.src.core.methods import cpdb_statistical_analysis_method

    kwargs = dict(
        cpdb_file_path=zips[0],
        meta_file_path=meta,
        counts_file_path=counts,
        counts_data=env_str("CPDB_COUNTS_DATA", "hgnc_symbol"),
        threshold=env_typed("CPDB_THRESHOLD", 0.1, float),
        iterations=env_typed("CPDB_ITERATIONS", 1000, int),
        score_interactions=True,  # v1 contract: always produce interaction_scores
        output_path=out_dir,
    )
    seed = env_typed("CPDB_SEED", None, int)
    if seed is not None:
        kwargs["seed"] = seed
    accepted = set(inspect.signature(cpdb_statistical_analysis_method.call).parameters)
    dropped = sorted(k for k in kwargs if k not in accepted)
    kwargs = {k: v for k, v in kwargs.items() if k in accepted}

    print(f"driver: db={os.path.basename(zips[0])} kwargs={sorted(kwargs)} "
          f"dropped_unsupported={dropped}", flush=True)
    result = cpdb_statistical_analysis_method.call(**kwargs)

    print("driver: result keys:", sorted(result) if hasattr(result, "keys") else type(result), flush=True)

    # Official outputs carry run timestamps in their names; rename to the
    # stable node contract (contents untouched).
    renames = {}
    for name in sorted(os.listdir(out_dir)):
        m = re.match(r"^statistical_analysis_(.+?)_\d{2}_\d{2}_\d{4}_\d{6}\.txt$", name)
        if m:
            fixed = f"cpdb_{m.group(1)}.txt"
            os.replace(os.path.join(out_dir, name), os.path.join(out_dir, fixed))
            renames[m.group(1)] = fixed

    # Provenance: the digest pins this image, this records what ran.
    db_sha = hashlib.sha256(open(zips[0], "rb").read()).hexdigest()
    provenance = {
        "package": "cellphonedb",
        "package_version": importlib.metadata.version("cellphonedb"),
        "database_file": os.path.basename(zips[0]),
        "database_sha256": db_sha,
        "params": {k: str(v) for k, v in kwargs.items()},
        "cluster_column": cluster_col,
        "meta_input": "provided" if env_str("AUTONOMICS_INPUT1", "") else "derived_from_obs",
        "renamed_outputs": renames,
    }
    with open(os.path.join(out_dir, "cpdb_provenance.json"), "w") as fh:
        json.dump(provenance, fh, indent=2, sort_keys=True)

    for name in sorted(os.listdir(out_dir)):
        path = os.path.join(out_dir, name)
        print(f"driver: output {name} ({os.path.getsize(path)} bytes)", flush=True)


if __name__ == "__main__":
    main()
