# Usage: python mkjob.py <job-name> <stage-folder-name-under-staging>
# Queues an elevated install of staging\<stage> via C:\dev\civiccast-trial\Install-Candidate.ps1.
# Then: powershell Start-ScheduledTask -TaskName ClaudeElevatedDevHelper  (the helper does not poll).
# NOTE: all paths are built with os.path.join on raw strings (an earlier version turned "\b" in "\backups" into a backspace).
import json, os, sys
j, stage = sys.argv[1], sys.argv[2]
b = r"C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-ds-oversight"
job = {
    "action": "RunTrustedPowerShellScript",
    "scriptPath": r"C:\dev\civiccast-trial\Install-Candidate.ps1",
    "arguments": ["-StageDir", os.path.join(b, "staging", stage), "-BackupDir", os.path.join(b, "backups", j)],
}
p = os.path.join(r"C:\dev\ClaudeElevatedHelper\queue", j + ".json")
with open(p, "w") as f:
    json.dump(job, f)
print(p, json.load(open(p))["arguments"])
