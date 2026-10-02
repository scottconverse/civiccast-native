# Reviewed Ollama model manifests (byte-exact)

The registry tags `gemma4:12b` and `gemma4:e4b` are mutable: they were re-published on 2026-09-27
(new weights, new draft layer) after we reviewed and pinned them, and the registry no longer serves
the old manifests by digest. A build that fetched the manifest by tag therefore failed
("manifest exceeds reviewed size"). These three files are the exact reviewed manifests, named by
their SHA-256, copied from a station that installed them from the reviewed registry state.
`scripts/provision_native_ollama_models.py` uses them (verified against the lock's size and SHA-256)
before touching the network. The model blobs are still fetched by pinned digest and verified.
To move to newer model builds, review the new manifest and update the lock and these files together.
