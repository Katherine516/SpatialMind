"""Golden-output checks: does the pipeline still produce recognisable biology?

The rest of the suite validates mechanics -- code runs, keys exist, refusals
fire. None of it would notice if the expression matrix were quietly filled with
technical noise. That is not hypothetical: Xenium control probes were 39% of the
breast panel and were driving PCA, defining four spurious clusters, and ranking as
markers, and that passed 146 green tests. It was caught by a human reading a
marker table.

These tests assert that well-known cell populations still fall out of real local
data. They are deliberately loose about cluster numbering and marker rank, and
strict about the thing that actually broke: no technical feature may ever appear
as a marker.
"""

import os
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
HEALTHY_BRAIN = os.path.join(
    ROOT, "data", "Xenium Human Brain", "Xenium_V1_FFPE_Human_Brain_Healthy_With_Addon_outs"
)
LYMPH_NODE = os.path.join(
    ROOT, "data", "Xenium lymph", "Xenium_V1_hLymphNode_nondiseased_section_outs"
)
BREAST = os.path.join(ROOT, "data", "Human_Breast_Biomarkers_S1_Top_outs")

# Cell populations that must be recoverable from an unlabelled section. Each is a
# marker family plus how many must co-occur in one cluster's top genes.
HEALTHY_BRAIN_POPULATIONS = {
    "astrocyte": ({"AQP4", "GJA1", "SOX9", "FGFR3"}, 2),
    "oligodendrocyte": ({"MOG", "CLDN11", "ERMN", "OPALIN", "UGT8", "CNDP1", "MOBP"}, 2),
    "microglia": ({"P2RY12", "GPR34", "CX3CR1", "RNASET2"}, 2),
    "opc": ({"PTPRZ1", "BCAN", "VCAN", "PDGFRA", "OLIG2"}, 2),
    "vascular": ({"FLT1", "PECAM1", "IGFBP7", "CLDN5"}, 2),
    "gabaergic": ({"GAD1", "GAD2", "SLC6A1"}, 2),
}

LYMPH_NODE_POPULATIONS = {
    "t_cell": ({"CD3D", "CD3E", "TRAC", "IL7R", "CD2"}, 2),
    "b_cell": ({"MS4A1", "CD79A", "BANK1", "CD19"}, 2),
    "myeloid": ({"AIF1", "MS4A6A", "MPEG1", "FGL2", "CD68"}, 2),
    "vascular": ({"PECAM1", "VWF", "CAVIN1"}, 2),
    "plasma_or_proliferating": ({"MZB1", "MKI67", "PCNA", "TNFRSF17", "SLAMF7"}, 2),
}


def _cluster_markers(dataset_path, max_records=4000, n_top=10):
    from spatialmind.ingestion import load_xenium
    from spatialmind.tools.implementations import marker_detection, qc_and_cluster

    dataset = load_xenium(dataset_path, max_records=max_records)
    qc_and_cluster(dataset, {"resolution": 0.55, "random_state": 0, "strict_engine": True})
    result = marker_detection(dataset, {"group_key": "cluster", "n_top": n_top, "strict_engine": True})
    return {
        str(group): [str(row["gene"]).upper() for row in rows]
        for group, rows in (result.metrics.get("markers_by_group") or {}).items()
    }


class BiologicalPlausibilityTests(unittest.TestCase):
    """Slow, data-dependent checks against real local sections."""

    def _assert_populations(self, dataset_path, populations, label):
        if not os.path.isdir(dataset_path):
            self.skipTest("local dataset not available: %s" % label)
        markers = _cluster_markers(dataset_path)
        self.assertGreaterEqual(len(markers), 3, "%s: too few clusters to be plausible" % label)
        for population, (family, required) in populations.items():
            hits = max((len(family & set(genes)) for genes in markers.values()), default=0)
            self.assertGreaterEqual(
                hits,
                required,
                "%s: no cluster carries >=%d of the %s markers %s. Found at most %d. "
                "Either the expression matrix is contaminated or clustering has regressed."
                % (label, required, population, sorted(family), hits),
            )

    def test_healthy_brain_recovers_expected_populations(self):
        self._assert_populations(HEALTHY_BRAIN, HEALTHY_BRAIN_POPULATIONS, "healthy brain")

    def test_lymph_node_recovers_expected_populations(self):
        self._assert_populations(LYMPH_NODE, LYMPH_NODE_POPULATIONS, "lymph node")

    def test_no_technical_feature_reaches_the_expression_matrix(self):
        """The regression that motivated this file, asserted where it is detectable.

        Checking markers is not enough: control probes entered the matrix on every
        panel but only reached the top-10 markers on a 209k-cell breast section
        with fourteen clusters. A marker-based check passes at any testable scale
        while the matrix is contaminated, which is precisely how this shipped.
        Assert on the analysis feature list instead -- deterministic, fast, and
        sensitive regardless of whether contamination happens to rank highly.
        """
        from spatialmind.ingestion import load_xenium
        from spatialmind.tools.implementations import (
            EXPRESSION_EXCLUDED_FEATURES,
            expression_feature_names,
            is_control_feature,
        )

        checked = 0
        for path, label in ((HEALTHY_BRAIN, "healthy brain"), (LYMPH_NODE, "lymph node"), (BREAST, "breast")):
            if not os.path.isdir(path):
                continue
            checked += 1
            dataset = load_xenium(path, max_records=1500)
            raw = list(dataset.genes)
            analysed = expression_feature_names(dataset)

            # The panel must actually contain control probes, or this proves nothing.
            raw_controls = [gene for gene in raw if is_control_feature(gene)]
            self.assertTrue(
                raw_controls,
                "%s: no control probes in the raw panel, so this check is vacuous" % label,
            )

            leaked = [gene for gene in analysed if is_control_feature(gene)]
            self.assertEqual(
                leaked, [],
                "%s: %d control probes reached the expression matrix, e.g. %s. They drive PCA and can "
                "define clusters out of technical noise." % (label, len(leaked), leaked[:5]),
            )
            leaked_qc = [gene for gene in analysed if gene.upper() in EXPRESSION_EXCLUDED_FEATURES]
            self.assertEqual(leaked_qc, [], "%s: QC pseudo-features reached the matrix: %s" % (label, leaked_qc))

        if not checked:
            self.skipTest("no local Xenium datasets available")

    def test_marker_tables_stay_free_of_technical_features(self):
        """Weaker than the matrix check above, but it is what a reader sees."""
        from spatialmind.tools.implementations import EXPRESSION_EXCLUDED_FEATURES, is_control_feature

        if not os.path.isdir(HEALTHY_BRAIN):
            self.skipTest("local dataset not available")
        for cluster, genes in _cluster_markers(HEALTHY_BRAIN).items():
            for gene in genes:
                self.assertFalse(is_control_feature(gene), "cluster %s markers include %s" % (cluster, gene))
                self.assertNotIn(gene, EXPRESSION_EXCLUDED_FEATURES)


if __name__ == "__main__":
    unittest.main()
