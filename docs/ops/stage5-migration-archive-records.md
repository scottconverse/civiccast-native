# Stage 5 Migration, Archive, Records, Producer, And Campus

Stage 5 verifies the software surfaces behind migration, archive, records,
recording, producer agenda, program log, as-run, metadata, paywall, and campus
access workflows. It is a local proof envelope over code, migrations, and focused
tests.

## Covered Surfaces

- Migration files for records, program log, as-run/EPG reporting, scheduled
  recording, recording/paywall merge, agenda, metadata, and paywall access.
- Archive retention presets and retention worker behavior.
- Signed records export, persistence, identity binding, PDF/A, and router flows.
- Recording service, store, production wiring, and recording router flows.
- Producer agenda creation, item import/sync, publish gate, and public agenda read.
- Program log materialization, occurrence handling, as-run capture, and reporting
  schedule adapter coverage.
- Metadata and paywall campus access surfaces.

## Focused Tests

The Stage 5 proof runs a focused pytest bundle over archive, records, recording,
program log, agenda, metadata, paywall, as-run capture, reporting adapter, migration
reversibility, and retention worker tests. The completion report blocks if the
focused tests are not passed.

## Not Claimed

Stage 5 local proof does not claim station migration execution, production archive
credential proof, or public campus deployment proof. Those require separate station
or deployment evidence with credentials and environment details captured outside
this local proof envelope.
