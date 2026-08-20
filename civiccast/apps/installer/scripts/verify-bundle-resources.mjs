// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

import { createHash } from "node:crypto";
import { existsSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";

const resources = resolve("src-tauri", "resources");
const required = [
  "bootstrap-manifest.json",
  "wheelhouse/WHEELHOUSE-MANIFEST.json",
  "gstreamer-runtime/gstreamer-runtime-linux-x86_64.tar.gz",
  "gstreamer-runtime/gstreamer-runtime-linux-x86_64.tar.gz.sha256"
];

for (const relative of required) {
  const path = resolve(resources, relative);
  if (!existsSync(path) || statSync(path).size === 0) {
    throw new Error(
      `Refusing to bundle an incomplete CivicCast installer: missing ${relative}. ` +
        "Use scripts/build_release_artifacts.py --python --wheelhouse --windows-installer."
    );
  }
}

const archive = resolve(resources, "gstreamer-runtime/gstreamer-runtime-linux-x86_64.tar.gz");
const checksum = resolve(resources, "gstreamer-runtime/gstreamer-runtime-linux-x86_64.tar.gz.sha256");
const expected = readFileSync(checksum, "utf8").trim().split(/\s+/)[0]?.toLowerCase();
const actual = createHash("sha256").update(readFileSync(archive)).digest("hex");

if (!expected || expected !== actual) {
  throw new Error(`Refusing to bundle CivicCast: GStreamer checksum mismatch (expected ${expected}, got ${actual}).`);
}

console.log("Installer bundle resources verified.");
