# Portable resident-browser test dependency

The dedicated tester already has Node24.17.0 and installed Edge/Chrome.
The September8 R2 inventory did not find Playwright Core in the known mission
repository paths. Provision the exact version pinned by the signed beta.5
portal lock, not a floating latest package:

- playwright-core1.59.1, Apache-2.0; no dependency or lifecycle script entries.
- URL: https://registry.npmjs.org/playwright-core/-/playwright-core-1.59.1.tgz
- Bytes:2458529; archive members465.
- SHA256:`22304c3d9106ed8372ff58656f645a93bc3a2b17df8567f1413079a730d8d6fa`.
- SHA512 SRI:`sha512-HBV/RJg81z5BiiZ9yPzIiClYV/QMsDCKUyogwH9p3MCP6IYjUFu/MActgYAvK0oWyV9NlwM3GLBjADyWgydVyg==`.

The helper checks both digests, rejects unsafe archive paths and links, and
extracts into a fresh mission-confined tools directory. It does not run npm,
install a browser, change PATH, alter the CivicCast installation, use an
operator token, call a station API, or launch the browser. Partial extraction
is preserved; only an empty staging directory is removed nonrecursively.

The unique tester directive returns a new prerequisite inventory and separate
portable-provisioning metadata. Browser execution remains a later post-soak
acceptance action. Tests use the actual tarball and a signed-source lock path,
but fake Node/Edge files: they prove archive/extraction contracts, not playback.
