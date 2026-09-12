# Install the fixed beta on the dedicated tester

Readiness R4 returned successfully in tester commit 5c2fb70d: administrator,
172 GB free disk, existing install and token present, healthy beta.5, no legacy
sampler task or soak-start flag, and HTTP 200 from the candidate manifest URL.
The repaired scheduled poller executed and published that diagnostic.

Execute AUTORUN-SEP11-FIXED-BETA-UPGRADE-R1.ps1 once. It uses the package at
soak/fixed-beta/39e7ec3c and creates a fresh mission directory:
C:\CivicCastSoak\missions\beta6-sep11-39e7ec3cbb4c.

The order fetches the exact candidate from http://192.168.0.135:8766/, verifies
the independently pinned manifest and installer SHA-256 values, all kit files,
the app pack source, and Scott Converse's valid installer signature. It performs
a normal in-place upgrade at C:\CivicCastHostStore\install. It preserves station
data and tokens. Any legacy beta sampler is paused, with its state recorded;
the three CivicCastSoak coordination tasks remain in place. No reboot occurs.

Candidate: 39e7ec3cbb4ccbeb3009ff3257dfc314010151f3
Signed build: 34633364038
Local Gate A: 34656528653. Clean and cross-version upgrade verdicts PASS;
download-only lane is still running. Identity truthfully retains PENDING until
all three verdicts pass. The candidate is not published.

Wait for the order to finish; do not manually replay it or clear its marker.
It verifies installed service/version and the daemon/strategy file hashes,
then emits FIXED_BETA_UPGRADE_RESULT_JSON_BEGIN/END on success or failure. The
poller publishes the log; the local result is saved as upgrade-result.json in
the mission directory. A failed install leaves its evidence for a later unique
repair order. This directive does not start the physical soak.
