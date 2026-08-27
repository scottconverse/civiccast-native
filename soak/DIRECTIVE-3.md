# DIRECTIVE 3 — USB drive: wipe and reuse (owner-ordered)

A USB drive is inserted in this machine. It holds OLD CivicCast install work. The owner
has ordered it deleted/formatted for fresh use.

1. Identify it precisely: enumerate removable drives (`Get-Volume` /
   `Get-Disk | Where-Object BusType -eq 'USB'`). Confirm the target by BOTH properties:
   it is on the USB bus AND its contents show old CivicCast material (list the root
   folders first and record them). NEVER touch C:, any internal disk, or any drive whose
   contents don't match. If more than one USB drive is present or the contents don't
   look like CivicCast work, do NOT format anything — commit soak/USB-AMBIGUOUS.md with
   what you found and continue the main mission without it.
2. Record in soak/USB.md before wiping: drive letter, size, filesystem, top-level folder
   listing (names only), so we have a record of what was destroyed.
3. Format it (quick format, NTFS, label CIVICCAST-TEST), elevated.
4. Use it as fresh scratch/workspace for this mission where useful (e.g. a second copy
   of archived evidence). It is expendable space.
5. Commit soak/USB.md with the before-listing, the format result, and the new state.

This does not change the main mission: after the machine's reboot, continue per
DIRECTIVE-2 → DIRECTIVE-1 (verify wipe state → clean install → 8h soak).
