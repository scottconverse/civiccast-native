# October 7 candidate corrections

The first hosted package build, run 37660584193 at source 7f67df99bfc0341c92c2d38a239f7b4938e1a863, was cancelled after candidate CI exposed defects. No package from that run is release evidence.

## Corrected and checked

- Asset retrieval validates HTTPS for both initial requests and redirects, retains bounded streaming and exact size/SHA verification, and passes Ruff/Bandit. The Rust test compile mistake and three stale pack expectations were corrected. The activation expectation independently names Whistle's runtime path.
- Hosted Windows Rust compilation and unit-test job passed at 505d24745a9085b18af3dab30e70c36cbc89da95 in run 37665380348, job 112943142585. The overall workflow was still running when this receipt was written; this is a job result, not a whole-workflow result.
- Built-in help keeps 635 contents entries and 29 images. Build-time WebP encoding reduces manual.json to 4,766,364 bytes, below the 5 MiB Git limit. Representative screenshot and diagram text were visually checked; this is not a review of every image. Pinned Pillow is a build/development dependency, imported lazily.
- Public-copy checking exempts only the exact existing non-affiliation notice; other vendor references and high-risk claims remain checked. OpenAPI regeneration changes version only, retaining 405 paths and 543 schemas.
- Tracked PDF, DOCX and render manifest match the exact PR-base Git blobs. Candidate PDFs/DOCX are rendered outside Git and retained with source/version/run/hash receipts. The hosted build, kit assembly, verifier and publisher preserve those exact files. Public manual links switch to versioned Beta 11 release assets at publication.
- The unused-import cleanup exposed a stale test patch target. The station-bundle test now patches the actual validator contract. Its 22 tests pass, including byte-identical model packs across build roots and product versions while the core changes. Local cache reuse still requires comparison with the final signed index and actual pack verification.

## Final combined check

```powershell
.\.venv\Scripts\python.exe -m pytest tests/native/test_build_native_station_bundle.py tests/installer/test_native_packs.py tests/native/test_whistle_asset_provisioning.py tests/native/test_app_payload_builder.py tests/native/test_station_runtime.py tests/native/test_native_bootstrap_builder.py tests/policy/test_native_beta_candidate_workflow.py tests/policy/test_native_installer_identity.py tests/docsite/test_render.py tests/policy/test_public_copy_legal.py tests/release/test_publish_beta_candidate.py tests/test_user_manual_render.py -q -k 'not fresh_render'
```

Result: **480 passed, 1 deselected in 20.07 seconds**. The fresh-PDF test was not repeated: the independent full manual suite had already passed 11 tests in 106.67 seconds, including one fresh render; its final historical-baseline assertion adjustment passed separately and in the combined run. Manual/API currentness, Ruff, lock consistency, actionlint, workflow budgets, shell/PowerShell syntax checks and diff checks also passed as documented by the responsible reviewers.

The root reviewed the manual staging/verification and workflow/publisher changes; the independent reviewer checked the coder's downloader and manual/policy changes. Five lenses for this correction scope found no unresolved source blocker: engineering/contract behavior, operator help, artifact documentation and provenance, static/security checks, and regression sensitivity. Artifact build, signatures, exact downloaded receipt, clean-install/activation and full-kit byte verification remain pending. Inherited broad-CI findings are not represented as green.

No station restart, model load, desktop runner start or Sandbox launch occurred. The continuing 20-minute observer remains active. The owner-directed gaming exclusion is preserved.

proved: combined affected tests 480 passed; independent focused review and named static checks passed; hosted Rust job passed on the stated earlier source commit | lane: Critical
