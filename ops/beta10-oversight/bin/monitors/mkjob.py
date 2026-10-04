# Usage: python mkjob.py <job-name> <stage-folder-name-under-staging>
# Queues an elevated install of staging\<stage> via C:\dev\civiccast-trial\Install-Candidate.ps1.
# Then: powershell Start-ScheduledTask -TaskName ClaudeElevatedDevHelper  (the helper does not poll).
# NOTE: compose paths from raw Windows path strings to avoid escape-sequence corruption.
import json
import sys
from pathlib import Path

j, stage = sys.argv[1], sys.argv[2]
b = r"C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-ds-oversight"
job = {
    "action": "RunTrustedPowerShellScript",
    "scriptPath": r"C:\dev\civiccast-trial\Install-Candidate.ps1",
    "arguments": [
        "-StageDir",
        str(Path(b) / "staging" / stage),
        "-BackupDir",
        str(Path(b) / "backups" / j),
    ],
}
p = Path(r"C:\dev\ClaudeElevatedHelper\queue") / (j + ".json")
with p.open("w") as f:
    json.dump(job, f)
with p.open() as f:
    arguments = json.load(f)["arguments"]
print(p, arguments)
