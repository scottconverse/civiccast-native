# SPDX-License-Identifier: Apache-2.0
"""CivicCast agentic pipeline policy checks.

These scripts encode the non-negotiable constraints an autonomous agent
run must satisfy before a manager role is allowed to PROMOTE the work.
Each script is standalone Python (3.12 stdlib only), exits 0 on pass,
exits 1 on fail with evidence printed to stdout.

Wired into pipeline runs by `.pipelines/feature.yaml` and `bugfix.yaml`
via the `policy` stage. Can also be run manually from a clean working
tree as `python scripts/policy/run_all.py`.
"""
