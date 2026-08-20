# Wheelhouse Duplicate Rationale

The v3.0.0-beta1 reroll wheelhouse contains two `cryptography` wheels:

- `cryptography-48.0.0-cp311-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl`
- `cryptography-49.0.0-cp311-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl`

Both files are hash-listed in `wheelhouse/WHEELHOUSE-MANIFEST.json` and are
release-artifact verified. The duplicate normalized project is accepted for this
public beta because the offline wheelhouse is a closed release artifact bundle,
not a resolver policy declaration; including both versions preserves the exact
dependency set captured during the reroll. Future builders may prune duplicate
normalized project names after resolver locking proves only one version is used.
