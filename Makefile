# SPDX-License-Identifier: Apache-2.0
# CivicCast top-level convenience targets.

.PHONY: help roadmap cleanroom cleanroom-build cleanroom-run cleanroom-shell

help:
	@echo "CivicCast make targets"
	@echo "  roadmap          Verify repo-status manifest (docs/spec/3.0/ROADMAP.status.yaml)"
	@echo "  cleanroom        Build the cleanroom image and run the full install gate"
	@echo "  cleanroom-build  Build the cleanroom image only"
	@echo "  cleanroom-run    Run the cleanroom against the current working tree"
	@echo "  cleanroom-shell  Drop into a bash shell inside the cleanroom image"

# Repo-verified project status. Fails closed if any row in the manifest claims a
# status the repository cannot prove (a false "built") or a built feature
# regressed. Run it any time to answer "where are we?" from the repo, not memory.
roadmap:
	python scripts/roadmap_status.py --check

# Bind-mount the project read-only into /work/civiccast inside the container.
# The runner script copies it into /tmp/cleanroom-work for writes, so the
# host tree is never touched.
#
# MSYS_NO_PATHCONV=1 prevents Git Bash on Windows from rewriting the Linux
# path inside the container argument. No-op on real Linux/macOS shells.
CLEANROOM_IMAGE = civiccast-cleanroom:latest
# Mount /var/run/docker.sock so the cleanroom's Gate 7 (TEST-002 — real-
# Postgres schedule contract) can use testcontainers to spawn a sibling
# postgres:17 container against the host Docker daemon. This is the
# standard "docker socket mount" pattern; the cleanroom container runs
# postgres alongside, not nested inside, itself. Windows Docker Desktop
# exposes the socket at the same Linux path inside its WSL2 backend.
CLEANROOM_RUN = MSYS_NO_PATHCONV=1 docker run --rm \
    -v "$$(pwd):/work/civiccast:ro" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    --add-host=host.docker.internal:host-gateway \
    $(CLEANROOM_IMAGE)

cleanroom: cleanroom-build cleanroom-run

cleanroom-build:
	docker build -f docker/cleanroom.Dockerfile -t $(CLEANROOM_IMAGE) .

cleanroom-run:
	$(CLEANROOM_RUN)

cleanroom-shell:
	MSYS_NO_PATHCONV=1 docker run --rm -it \
	    -v "$$(pwd):/work/civiccast:ro" \
	    -v /var/run/docker.sock:/var/run/docker.sock \
	    --add-host=host.docker.internal:host-gateway \
	    $(CLEANROOM_IMAGE) bash
