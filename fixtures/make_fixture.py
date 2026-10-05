#!/usr/bin/env python3
"""Tiny fixture: 3 clusters, real CellPhoneDB v5 LR genes up-regulated in
specific clusters so statistical_analysis produces non-empty results."""
import numpy as np
import pandas as pd
import anndata as ad

rng = np.random.default_rng(7)

# Real hgnc symbols present in the curated v5 database.
LR_GENES = [
    "TGFB1", "TGFBR1", "TGFBR2", "IL6", "IL6R", "IL6ST",
    "CXCL12", "CXCR4", "MIF", "CD74", "CCL2", "CCR2",
    "FLT1", "VEGFA", "EGF", "EGFR", "WNT5A", "FZD5",
]
FILLER = [f"GENE{i:03d}" for i in range(80)]
genes = LR_GENES + FILLER

n_per = 80
clusters = ["T_cells", "Macrophages", "Fibroblasts"]
counts = rng.poisson(1.2, size=(n_per * len(clusters), len(genes))).astype(np.float32)

# Signal: ligand up in source cluster, receptor up in target cluster.
def up(gene, cluster, factor=14):
    ci = clusters.index(cluster)
    gi = genes.index(gene)
    counts[ci * n_per:(ci + 1) * n_per, gi] += rng.poisson(factor, size=n_per).astype(np.float32)

up("TGFB1", "Fibroblasts"); up("TGFBR1", "T_cells"); up("TGFBR2", "T_cells")
up("IL6", "Macrophages"); up("IL6R", "T_cells"); up("IL6ST", "T_cells")
up("CXCL12", "Fibroblasts"); up("CXCR4", "T_cells")
up("MIF", "Macrophages"); up("CD74", "Macrophages")
up("VEGFA", "Fibroblasts"); up("FLT1", "Macrophages")
up("EGF", "Fibroblasts"); up("EGFR", "Macrophages")
up("CCL2", "Macrophages"); up("CCR2", "T_cells")

obs_cluster = [c for c in clusters for _ in range(n_per)]
adata = ad.AnnData(
    X=counts,
    obs=pd.DataFrame({"cluster": obs_cluster}),
    var=pd.DataFrame(index=genes),
)
adata.obs_names = [f"cell_{i:04d}" for i in range(adata.n_obs)]
adata.write_h5ad("/workdir/fixture.h5ad")
print(f"fixture: {adata.n_obs} cells x {adata.n_vars} genes -> /workdir/fixture.h5ad")
