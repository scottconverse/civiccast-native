# AUTORUN-8 station setup + three-channel soak (2h candidate e5020746)
- mission: soak8-e1acfe6
- host: DESKTOP-VBMA6O5
- utc: 20260905T075613Z
- kit: C:\CivicCastSoak\kit-e5020746fa40e7a3f1a160d3a8e1add5c3b57786
- DryRun: False

station healthy; schema=current db_revision=
first-admin POST failed: The remote server returned an error: (409) Conflict. :: 
STALLED: no staff token. Ship a follow-up autorun with a recovery path.

## openapi paths mentioning setup/first-admin
/api/setup/station-state
/api/setup/storage
/api/setup/first-admin
/api/setup/recovery-kit/acknowledge
/api/setup/login
/api/setup/recover
/api/staff/installer/first-admin-contract
/api/staff/installer/first-admin
/api/staff/installer/source-setup
/api/staff/installer/source-setup/live-source
/api/staff/installer/source-setup/sample-upload
/api/staff/cable/commissioning/channel-setup
