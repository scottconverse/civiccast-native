# DIRECTIVE 7 — soak72-9573d4a: MISSION CLOSED

(no Trigger line: this directive is informational; do not start or restart the soak clock)

The owner cancelled this soak on 2026-09-03. If you are the agent on this machine and you read this: run, elevated,
`Unregister-ScheduledTask -TaskName CivicCastSoak-Poll,CivicCastSoak-Heartbeat,CivicCastSoak-Boot -Confirm:$false`,
commit `soak/CLOSED.md` with the UTC time to your branch, and stop. Do not install anything. Thank you.
