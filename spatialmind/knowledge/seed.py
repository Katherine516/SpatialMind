"""Original, concise product/method notes shipped without user data."""

VERSION = "2026-10-15.1"
SOURCES = [
    ("library", "Local datasets and removal", "",
     "SpatialMind imports data on your own computer. Linking an existing Xenium folder does not copy it. "
     "Removing a dataset from the library hides its registration and preserves original files and reports. "
     "Removed entries can be restored. A fresh installation includes no research datasets."),
    ("xenium", "Xenium input bundles", "https://www.10xgenomics.com/support/software/xenium-onboard-analysis/latest/analysis/xoa-output-understanding-outputs",
     "A .xenium experiment file describes an experiment; it is not the complete expression dataset. "
     "Keep its associated cell table and expression matrix together. Morphology and boundaries support visual inspection. "
     "SpatialMind checks missing components separately from recognizing the file type. Link the complete folder for large experiments."),
    ("moran", "Moran's I and spatial structure", "https://scanpy.readthedocs.io/en/stable/",
     "Moran's I measures spatial autocorrelation relative to a specified neighbor graph. Positive values can indicate similar "
     "measurements occurring near one another. Interpret effect size together with the null model, permutation count and "
     "multiple-testing correction. A spatial pattern does not establish a cell identity or a causal mechanism."),
    ("neighborhood", "Neighborhood enrichment and co-occurrence", "https://squidpy.readthedocs.io/en/stable/",
     "Neighborhood enrichment compares observed label adjacency with a permutation-based null. Region-stratified tests "
     "condition permutations on eligible regions. Distance-dependent co-occurrence describes associations over distance "
     "scales. Results depend on graph construction, labels, tissue boundaries and null assumptions. Proximity is not proof "
     "of signaling, interaction or causality."),
    ("review", "Expert labels, regions and readiness", "",
     "Expert cell labels require a qualified human reviewer, recorded identity, date, confidence and supporting evidence. "
     "Anatomical regions require appropriate tissue evidence and review; expression-derived domains are not automatically anatomy. "
     "A reference prediction, chat message, ontology term or uploaded note cannot approve labels, regions or protocols. "
     "Descriptive clustering remains separate from validated biological analysis."),
    ("clustering", "Clustering and annotation", "https://scanpy.readthedocs.io/en/stable/",
     "Clustering groups cells by measured features and analysis choices. Cluster identifiers are not cell-type labels. "
     "Annotation needs marker evidence, appropriate references and uncertainty assessment. Reference-assisted predictions "
     "must remain identifiable as predictions. An independently reviewed donor is needed to evaluate external generalization."),
    ("ontology", "Cell Ontology and astrocytes", "https://obophenotype.github.io/cell-ontology/",
     "Cell Ontology provides standardized cell-type names and identifiers. Astrocyte has identifier CL:0000127. "
     "An ontology definition supplies vocabulary, not evidence that a particular Xenium cell is an astrocyte. "
     "Cell lineage and malignant, nonmalignant or uncertain state must be treated separately."),
    ("h5ad", "AnnData and H5AD references", "https://anndata.readthedocs.io/en/stable/",
     "AnnData stores a feature matrix with observation and feature metadata. An H5AD file may also contain layers and "
     "embeddings. Verify whether the selected matrix contains raw counts, normalized values or another representation. "
     "UMAP coordinates are not tissue positions. Human reference suitability also depends on tissue, assay, gene overlap, "
     "donor identity, label provenance and licensing."),
    ("reliability", "Claim-level reliability and evidence", "",
     "A biological reliability score must come from the actual analysis and its recorded evidence. Literature retrieval "
     "similarity and a language model's confidence are not probabilities that a biological claim is true. Report missing "
     "components, robustness settings and review limitations. Knowledge answers cannot increase an experimental reliability score."),
    ("panel", "Targeted panels and gene interpretation", "",
     "A targeted spatial transcriptomics panel measures a selected set of genes. A gene absent from the panel was not "
     "measured; this does not establish absent expression. Marker detection is conditional on the measured panel, grouping "
     "and statistical design. Accessibility-inferred gene activity is not measured RNA expression."),
    ("privacy", "Privacy and offline answers", "",
     "The default Ask mode retrieves local source passages without contacting a language-model service. It is source search, "
     "not a generative local model. Optional hosted generation requires explicit sharing consent. Do not send raw biomedical "
     "data or identifiers to a provider. Uploaded lab notes are unreviewed until a person records a source-review decision."),
]
