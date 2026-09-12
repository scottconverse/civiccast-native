# Readiness after tester control-loop repair

Tester repair report edf2ed3e and scheduled diagnostic log 7b1a2b4d establish
execution and evidence return. R1/R2 failed during JSON serialization; their
failures are preserved. Do not replay them or remove their done markers.

Run the new AUTORUN-SEP11-FIXED-BETA-READINESS-R4.ps1 once through the poller.
It reports only scalar system/task/service facts, token presence, health and
candidate manifest reachability. It changes no station state and reads no token
contents. Fresh plain strings prevent PowerShell provider metadata expansion.
The repaired poller returns its output under soak/autorun-logs.

This is readiness collection, not an installation or soak order. Candidate
39e7ec3cbb4ccbeb3009ff3257dfc314010151f3 is still unpublished. Local Gate A upgrade
installation exited zero and acceptance continues; no final upgrade PASS yet.
