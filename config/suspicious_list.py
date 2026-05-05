SUSPICIOUS_KEYWORDS: frozenset[str] = frozenset({
    # Study design & reporting
    "study", "trial", "review", "analysis", "cohort", "survey",
    "registry", "database", "record", "protocol", "guideline",
    "report", "reporting", "documentation",
    # Study participants & groups
    "group", "arm", "patient", "participant", "subject",
    "control", "intervention", "allocation", "randomization",
    "sample", "population", "cohort",
    # Outcomes & statistics
    "outcome", "endpoint", "result", "finding", "data",
    "score", "scale", "index", "rate", "ratio", "percentage",
    "mean", "median", "odds", "hazard", "confidence", "p-value",
    "follow-up", "baseline", "duration",
    # Methodology terms
    "method", "methodology", "technique", "approach", "strategy",
    "criteria", "inclusion", "exclusion", "consent",
    "bias", "limitation", "heterogeneity", "blinding",
    # Animal / basic science
    "model", "assay", "vitro", "vivo", "murine", "rodent",
    "pcr", "rrna", "sequencing", "staining", "immunohistochemistry",
    "macrophage", "fibroblast", "keratinocyte", "cytokine",
    # Demographics / admin
     "nurse", "physician",
    "knowledge", "attitude",
    # Bibliometric
    "pubmed", "scopus", "prospero", "prisma", "cochrane",
    "regression", "hazard", "propensity", "heterogeneity",
})
