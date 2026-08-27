# Directive channel broken

Recorded after the owner-mandated fetch-and-show sequence on 2026-08-27.

Commands run exactly:

```text
git -C C:\CivicCastSoak\repo fetch origin
git -C C:\CivicCastSoak\repo show origin/tester/soak8h-99db2c6-directives:soak/DIRECTIVE-5.md
git -C C:\CivicCastSoak\repo show origin/tester/soak8h-99db2c6-directives:soak/DIRECTIVE-5b.md
```

Combined output:

```text
From https://github.com/scottconverse/civiccast-native
 * branch            tester/soak8h-99db2c6-DESKTOP-VBMA6O5 -> FETCH_HEAD
   f01590f..407e507  main       -> origin/main
fatal: invalid object name 'origin/tester/soak8h-99db2c6-directives'.
fatal: invalid object name 'origin/tester/soak8h-99db2c6-directives'.
```

Result: neither required directive could be read after the required fetch. No LPM rehearsal or new soak actions were started.
