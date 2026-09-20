# xenium_healthy_brain_mini

Subsampled from `Xenium_V1_FFPE_Human_Brain_Healthy_With_Addon_outs` by `scripts/build_test_fixture.py` so
`tests/test_biological_plausibility.py` runs without the full dataset.

- 4000 cells, deterministic even-index sample
- 319 panel genes plus 40 control probes (the contamination check needs controls present)
- no morphology, no boundaries: review-ready, not gate-ready
