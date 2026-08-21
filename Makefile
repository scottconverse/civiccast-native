# SPDX-License-Identifier: Apache-2.0
# CivicCast top-level convenience targets.

.PHONY: help roadmap

help:
	@echo "CivicCast make targets"
	@echo "  roadmap          Verify repo-status manifest (docs/spec/3.0/ROADMAP.status.yaml)"
	@echo ""
	@echo "There is no automated clean-box/cleanroom gate in this repository."
	@echo "The retired ci-cleanroom-e2e.yml Docker/Linux full-install gate did"
	@echo "not come across when the WSL2 lane was retired (docker/ was excluded"
	@echo "with it), and nothing replaced it. See docs/ops/gate-a.md for the"
	@echo "native line's station-acceptance gate."

# Repo-verified project status. Fails closed if any row in the manifest claims a
# status the repository cannot prove (a false "built") or a built feature
# regressed. Run it any time to answer "where are we?" from the repo, not memory.
roadmap:
	python scripts/roadmap_status.py --check
