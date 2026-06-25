# Wound Ontology build — ODK-compatible without Docker
# Targets: imports | test | release | clean
#
# Prerequisites: robot (https://robot.obolibrary.org) on PATH

ONT         = wond
EDIT        = src/ontology/$(ONT)-edit.owl
IMPORTS_DIR = src/ontology/imports
SPARQL_DIR  = src/ontology/sparql
RELEASE_DIR = output/release

# Path to source OWL/OBO files (override on CLI if needed)
# Note: spaces in path are handled via single-quoting in each recipe
ONTO_DIR ?= /Users/Strubbelig/Library/Mobile Documents/com~apple~CloudDocs/Forschung/Flap ontology/Import-Ontologien

ROBOT     = robot
SLME_METHOD = bot

# ── Import module definitions ─────────────────────────────────────────────────
# Format: PREFIX : source_filename
# Prefixes already small (BFO, COB, IAO, NCBITaxon) are skipped

IMPORT_CHEBI   = $(IMPORTS_DIR)/chebi_import.owl
IMPORT_DOID    = $(IMPORTS_DIR)/doid_import.owl
IMPORT_HP      = $(IMPORTS_DIR)/hp_import.owl
IMPORT_GO      = $(IMPORTS_DIR)/go_import.owl
IMPORT_PATO    = $(IMPORTS_DIR)/pato_import.owl
IMPORT_OBI     = $(IMPORTS_DIR)/obi_import.owl
IMPORT_DRON    = $(IMPORTS_DIR)/dron_import.owl
IMPORT_OGMS    = $(IMPORTS_DIR)/ogms_import.owl

ALL_IMPORTS = $(IMPORT_CHEBI) $(IMPORT_DOID) $(IMPORT_HP) $(IMPORT_GO) \
              $(IMPORT_PATO) $(IMPORT_OBI) $(IMPORT_DRON) $(IMPORT_OGMS)

# ── Top-level targets ─────────────────────────────────────────────────────────

.PHONY: all imports test release clean help

all: imports test

help:
	@echo "Targets:"
	@echo "  imports   Regenerate all SLME import modules from source ontologies"
	@echo "  test      Run SPARQL QC checks against the edit file"
	@echo "  release   Merge edit + imports into release OWL and OBO"
	@echo "  clean     Remove generated import modules"

# ── Import modules ────────────────────────────────────────────────────────────

imports: $(ALL_IMPORTS)
	@echo "All import modules up to date."

$(IMPORT_CHEBI): $(IMPORTS_DIR)/chebi_terms.txt
	@echo "[CHEBI] extracting module..."
	$(ROBOT) extract --method $(SLME_METHOD) \
	  --input '$(ONTO_DIR)/chebi.obo' \
	  --term-file $< --imports EXCLUDE \
	  --output $@

$(IMPORT_DOID): $(IMPORTS_DIR)/doid_terms.txt
	@echo "[DOID] extracting module..."
	$(ROBOT) extract --method $(SLME_METHOD) \
	  --input '$(ONTO_DIR)/doid.owl' \
	  --term-file $< --imports EXCLUDE \
	  --output $@

$(IMPORT_HP): $(IMPORTS_DIR)/hp_terms.txt
	@echo "[HP] extracting module..."
	$(ROBOT) extract --method $(SLME_METHOD) \
	  --input '$(ONTO_DIR)/hp.obo' \
	  --term-file $< --imports EXCLUDE \
	  --output $@

$(IMPORT_GO): $(IMPORTS_DIR)/go_terms.txt
	@echo "[GO] extracting module..."
	$(ROBOT) extract --method $(SLME_METHOD) \
	  --input '$(ONTO_DIR)/go.obo' \
	  --term-file $< --imports EXCLUDE \
	  --output $@

$(IMPORT_PATO): $(IMPORTS_DIR)/pato_terms.txt
	@echo "[PATO] extracting module..."
	$(ROBOT) extract --method $(SLME_METHOD) \
	  --input '$(ONTO_DIR)/pato.owl' \
	  --term-file $< --imports EXCLUDE \
	  --output $@

$(IMPORT_OBI): $(IMPORTS_DIR)/obi_terms.txt
	@echo "[OBI] extracting module..."
	$(ROBOT) extract --method $(SLME_METHOD) \
	  --input '$(ONTO_DIR)/OBI.rdf' \
	  --term-file $< --imports EXCLUDE \
	  --output $@

$(IMPORT_DRON): $(IMPORTS_DIR)/dron_terms.txt
	@echo "[DRON] extracting module..."
	$(ROBOT) extract --method $(SLME_METHOD) \
	  --input '$(ONTO_DIR)/dron.owl' \
	  --term-file $< --imports EXCLUDE \
	  --output $@

$(IMPORT_OGMS): $(IMPORTS_DIR)/ogms_terms.txt
	@echo "[OGMS] extracting module..."
	$(ROBOT) extract --method $(SLME_METHOD) \
	  --input '$(ONTO_DIR)/ogms.owl' \
	  --term-file $< --imports EXCLUDE \
	  --output $@

# ── QC / test ─────────────────────────────────────────────────────────────────

CATALOG = src/ontology/catalog-v001.xml

test: $(EDIT)
	@echo "Running SPARQL QC checks..."
	@mkdir -p $(SPARQL_DIR)/results
	$(ROBOT) verify \
	  --catalog $(CATALOG) \
	  --input $(EDIT) \
	  --queries $(SPARQL_DIR)/*.sparql \
	  --output-dir $(SPARQL_DIR)/results
	@echo "QC passed."

# ── Release ───────────────────────────────────────────────────────────────────

release: $(EDIT) imports
	@mkdir -p $(RELEASE_DIR)
	@echo "Merging edit file with import modules..."
	$(ROBOT) merge \
	  --catalog $(CATALOG) \
	  --input $(EDIT) \
	  $(foreach i,$(ALL_IMPORTS),--input $(i)) \
	  --include-annotations true \
	  annotate \
	  --ontology-iri "http://purl.obolibrary.org/obo/wond.owl" \
	  --output $(RELEASE_DIR)/$(ONT).owl
	$(ROBOT) convert \
	  --input $(RELEASE_DIR)/$(ONT).owl \
	  --output $(RELEASE_DIR)/$(ONT).obo
	@echo "Release written to $(RELEASE_DIR)/"

# ── Clean ─────────────────────────────────────────────────────────────────────

clean:
	rm -f $(ALL_IMPORTS)
	rm -rf $(SPARQL_DIR)/results
	@echo "Cleaned generated import modules."
