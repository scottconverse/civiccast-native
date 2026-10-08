# Usage: python mkjob.py <job-name> <stage-folder-name-under-staging>
# Queues an elevated install of staging\<stage> via C:\dev\civiccast-trial\Install-Candidate.ps1.
# Then: powershell Start-ScheduledTask -TaskName ClaudeElevatedDevHelper  (the helper does not poll).
# NOTE: all paths are built with os.path.join on raw strings (an earlier version turned "\b" in "\backups" into a backspace).
import json
import sys
from pathlib import Path

j, stage = sys.argv[1], sys.argv[2]
b = Path(r"C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-ds-oversight")
job = {
    "action": "RunTrustedPowerShellScript",
    "scriptPath": r"C:\dev\civiccast-trial\Install-Candidate.ps1",
    "arguments": ["-StageDir", str(b / "staging" / stage), "-BackupDir", str(b / "backups" / j)],
}
p = Path(r"C:\dev\ClaudeElevatedHelper\queue") / f"{j}.json"
with p.open("w", encoding="utf-8") as f:
    json.dump(job, f)
print(p, json.loads(p.read_text(encoding="utf-8"))["arguments"])
