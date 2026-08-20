# v3.0.0-beta1 clean Windows install proof

Status: `partial`
Dry run: `false`
VM booted: `false`
Release manifest: `artifacts\release\v3.0.0-beta1-reroll-8bef23b9\civiccast-3.0.0-beta1-release-artifacts-manifest.json`

Result: `runtime-only proof; a native isolated Windows installer proof is still required before public release.`

## Attempts

### hyper-v-vm

- Status: `blocked`
- Command: `Get-VM -Name civiccast-beta-clean`
- Return code: `1`
- Blocker evidence: Get-VM : The term 'Get-VM' is not recognized as the name of a cmdlet, function, script file, or operable program.
Check the spelling of the name, or if a path was included, verify that the path is correct and try again.
At line:1 char:1
+ Get-VM -Name civiccast-beta-clean
+ ~~~~~~
    + CategoryInfo          : ObjectNotFound: (Get-VM:String) [], CommandNotFoundException
    + FullyQualifiedErrorId : CommandNotFoundException

### windows-sandbox

- Status: `blocked`
- Command: `Get-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM`
- Return code: `1`
- Blocker evidence: Get-WindowsOptionalFeature : The requested operation requires elevation.
At line:1 char:1
+ Get-WindowsOptionalFeature -Online -FeatureName Containers-Disposable ...
+ ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : NotSpecified: (:) [Get-WindowsOptionalFeature], COMException
    + FullyQualifiedErrorId : Microsoft.Dism.Commands.GetWindowsOptionalFeatureCommand

### wsl2-fresh-distro

- Status: `available`
- Command: `wsl.exe --list --verbose`
- Return code: `0`
- Blocker evidence: Host capability command succeeded; no fresh isolated install was executed without a configured disposable target.

### wsl2-fresh-user

- Status: `passed`
- Command: `wsl.exe -d Ubuntu-24.04 --exec bash -lc 'set -euo pipefail; sandbox=$(mktemp -d); trap \'rm -rf "$sandbox"\' EXIT; python3 -m venv "$sandbox/venv"; "$sandbox/venv/bin/python" -m pip install --no-index --find-links \'/mnt/c/CivicCastTester/v3-beta-release-prep/artifacts/release/v3.0.0-beta1-reroll-8bef23b9/wheelhouse\' \'/mnt/c/CivicCastTester/v3-beta-release-prep/artifacts/release/v3.0.0-beta1-reroll-8bef23b9/civiccast-3.0.0b1-py3-none-any.whl[captions-runtime]\'; "$sandbox/venv/bin/python" -c \'import civiccast; print(civiccast.__version__)\''`
- Return code: `0`
- Blocker evidence: none
