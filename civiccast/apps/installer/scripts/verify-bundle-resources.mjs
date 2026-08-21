// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

import { existsSync, statSync } from "node:fs";
import { resolve } from "node:path";

// Native-Windows product only. The old WSL2 lane bundled a Linux wheelhouse
// and a Linux GStreamer runtime tarball into the installer so it could hand
// them off to a WSL2 distro; that lane was retired (2026-08-19) and nothing
// in the shipped app reads those resources at runtime -- only
// `bootstrap-manifest.json` is (see `main.rs`'s `resource_dir` /
// `headless_resource_dir` lookups). The audited native runtime tree is
// staged separately via `scripts/build_native_installer.py` and
// `tauri.native.conf.json`'s own `bundle.resources`.
const resources = resolve("src-tauri", "resources");
const required = ["bootstrap-manifest.json"];

for (const relative of required) {
  const path = resolve(resources, relative);
  if (!existsSync(path) || statSync(path).size === 0) {
    throw new Error(
      `Refusing to bundle an incomplete CivicCast installer: missing ${relative}.`
    );
  }
}

console.log("Installer bundle resources verified.");
