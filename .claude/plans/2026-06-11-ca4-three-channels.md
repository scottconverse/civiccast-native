# CA-4: Three-Channel Concurrency + Health Rollup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Part of the cable-automation sprint (master: 2026-06-11-cable-automation-sprint-master.md). CA-1=#141, CA-2=#142, CA-3=PR pending.

**Goal:** Three concurrent automated channels are a first-class, observable configuration: the automation loop provably handles N channels with independent state/latches, the operator sees an at-a-glance rollup in System Health, and the runbook documents the three-channel single-box posture.

**Verified current state:** The automation loop already iterates every enabled config (CA-2) — concurrency exists structurally but is UNPROVEN beyond one channel, and per-channel latch isolation has no multi-channel test. `StaffEgressChannelSummary` (egress/router.py:75) already serves per-channel state+health to the console. System Health (`installer/service.py` HealthCheckItem checks) has no channel-automation item.

**Scope (deliberately tight — the guide editor UX is CA-5):**
1. **Multi-channel automation tests** (`tests/egress/test_automation.py` additions): three channels in one `run_once` — independent auto-start latches (one dark+flagged starts; one live stays untouched; one disabled skipped), independent slate-replan latches, per-channel command isolation (commands enqueued for the right channel only), and a crash-of-one-channel pass (fake daemon drops one channel's process; only that channel gets a re-start).
2. **System Health rollup**: new `HealthCheckItem` "channel-automation" in the installer system-health report — green when every `auto_start` channel's last state is ON_AIR/FALLBACK_SLATE-with-reason, yellow when an automated channel is dark/ERROR, gray/info when no channels are automated. Built from `EgressStore.list_configs()` + `read_state()` per channel. Wire through the existing system-health builder seam (find where egress feeds it — the operator console already shows "Outgoing channel feed" from egress health; mirror that integration point). TDD against the installer system-health tests' style.
3. **Resource sanity + runbook**: docs/ops/channel-egress-runbook.md gains a "running three channels on one box" section: 3× ffmpeg encoder cost expectations, work-dir layout per channel, the no-CLI-plus-inline rule, and what the health rollup means. No code claims about load we haven't measured — CA-8's 24h run produces the actual numbers.

**Steps:** branch `work/ca4-three-channels` → failing tests (automation multi-channel + health item) → implement → docs → full gate → PR → merge. Small stage; sets up CA-5 (guide editor) and CA-8 (the 24h three-channel proof this stage's tests rehearse in miniature).
