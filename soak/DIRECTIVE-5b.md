# DIRECTIVE 5b — amendment to DIRECTIVE 5: install FROM the USB stick

The USB stick in this machine becomes both the install medium for today's rehearsal AND
tomorrow's physical delivery vehicle to LPM. Changes to DIRECTIVE 5:

## Phase 2 addition (after the LAN download + verification of kit13):
1. Identify the USB stick per DIRECTIVE 3's safety rules (USB bus + confirm contents;
   never an internal disk; if ambiguous commit soak/USB-AMBIGUOUS.md and continue the
   mission from C:\CivicCastSoak\kit13 WITHOUT the USB — the mission never blocks on it).
   If DIRECTIVE 3's format was never executed, do it now (record before-contents first,
   quick format NTFS, label CIVICCAST-TEST).
2. CAPACITY CHECK: the kit is ~27 GB. If the stick is smaller, do NOT try — commit
   soak/USB.md saying "too small (<size>)", and continue installing from
   C:\CivicCastSoak\kit13 as originally directed.
3. If it fits: copy the ENTIRE kit13 tree to the stick (e.g. E:\civiccast-kit-407e507\).
   Then VERIFY THE COPY BY HASH: SHA-256 every file on the stick against the source
   (Get-FileHash both sides; counts and every hash must match — a prior fleet incident
   proved size-identical copies can be hash-corrupt). Record counts + total bytes +
   "all hashes match" in soak/USB.md. If any mismatch: recopy the mismatched files once;
   if still mismatched, declare the stick unreliable in soak/USB.md and fall back to
   the local kit13 folder for the install.

## Phase 3 change:
Run the installer FROM THE USB PATH (e.g. & "E:\civiccast-kit-407e507\<setup exe>" /S
/D=C:\CivicCastHostStore\install) — this rehearses tomorrow's exact medium. Everything
else in Phase 3 (adopt-over-preserved-data expectations, evidence, failure handling)
unchanged. Note in soak/INSTALL-2.md that the install ran from USB.

## After the soak completes (or in parallel during it):
Leave the kit on the stick — it travels to LPM tomorrow. Nothing else changes.
