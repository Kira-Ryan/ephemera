# Ephemera - task entry points.
# Windows users: run via Git Bash ("make" from Git for Windows or via scoop/choco make).
# The OpenTimestamps client does not run on Windows; the stamp targets use Docker (Linux engine).

SPOOL   ?= data/raw/spool
CONTACT ?= $(EPHEMERA_CONTACT)
CYCLE   ?= $(shell ls -d $(SPOOL)/cycle_* 2>/dev/null | sort | tail -1)

.PHONY: help test lint poll poll-test watch witness stamp upgrade verify probes

help:
	@echo "test           claims lint + pytest over archive/tests (local fake feed, no network)"
	@echo "lint           claims-register lint over the outward documents"
	@echo "poll           pull one full cycle into $(SPOOL) (16 workers; CONTACT=you@example.org)"
	@echo "poll-test      pull a 5-file slice into $(SPOOL)/partial (smoke test; never gets a root)"
	@echo "watch          run the watcher against $(SPOOL) until interrupted"
	@echo "witness        one witnessing pass over $(SPOOL) (stamp, upgrade, Wayback)"
	@echo "stamp          OpenTimestamps-stamp the latest complete cycle's root.txt (Docker)"
	@echo "upgrade        fold Bitcoin attestations into the latest cycle's proof (Docker)"
	@echo "verify         verify the latest cycle's proof (Docker)"
	@echo "probes         list probe folders and their status lines"

lint:
	python tools/claims_lint.py

test: lint
	python -m pytest archive/tests tools/tests infra/tests -q -p no:cacheprovider

poll:
	@test -n "$(CONTACT)" || (echo "set CONTACT=you@example.org (or EPHEMERA_CONTACT)"; exit 1)
	python archive/poll.py --spool $(SPOOL) --workers 16 --contact "$(CONTACT)"

poll-test:
	@test -n "$(CONTACT)" || (echo "set CONTACT=you@example.org (or EPHEMERA_CONTACT)"; exit 1)
	python archive/poll.py --spool $(SPOOL) --workers 16 --limit 5 --contact "$(CONTACT)"

watch:
	@test -n "$(CONTACT)" || (echo "set CONTACT=you@example.org (or EPHEMERA_CONTACT)"; exit 1)
	python archive/run_cycle.py --spool $(SPOOL) --workers 16 --contact "$(CONTACT)"

witness:
	@test -n "$(CONTACT)" || (echo "set CONTACT=you@example.org (or EPHEMERA_CONTACT)"; exit 1)
	python archive/witness.py --spool $(SPOOL) --contact "$(CONTACT)" --once

stamp:
	@test -n "$(CYCLE)" || (echo "no cycle in $(SPOOL)"; exit 1)
	@test -f "$(CYCLE)/root.txt" || (echo "$(CYCLE) has no root.txt (incomplete cycle) - refusing to stamp"; exit 1)
	MSYS_NO_PATHCONV=1 docker run --rm -v "$(abspath $(CYCLE)):/w" python:3.12-slim \
	  sh -c "pip install -q opentimestamps-client && cd /w && ots stamp root.txt && ots info root.txt.ots | head -5"

upgrade:
	MSYS_NO_PATHCONV=1 docker run --rm -v "$(abspath $(CYCLE)):/w" python:3.12-slim \
	  sh -c "pip install -q opentimestamps-client && cd /w && ots upgrade root.txt.ots"

verify:
	MSYS_NO_PATHCONV=1 docker run --rm -v "$(abspath $(CYCLE)):/w" python:3.12-slim \
	  sh -c "pip install -q opentimestamps-client && cd /w && ots verify root.txt.ots"

probes:
	@for d in probes/p*/; do printf "%-24s " "$$d"; grep -m1 -E '^\*\*(Status|Question)' "$$d/README.md" 2>/dev/null | cut -c1-90 || echo "(no README)"; done
