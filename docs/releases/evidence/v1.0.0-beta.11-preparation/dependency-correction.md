# Native dependency correction

Before final packaging, source review confirmed that uploaded PDF processing uses pypdf's `PdfReader` and `extract_text`, which reach upstream Moderate malformed-PDF denial-of-service advisories in 6.14.2. The floor is now 6.19.0. urllib3 is raised from 2.7.0 to 2.8.0 in both CDN extras; it ships through botocore. The reported urllib3 advisories require particular streaming/proxy conditions that were not established as unconditional product exposure. Updating it is a focused preventive correction, not a claim that CivicCast was demonstrated exploitable through those paths.

The native requirements resolver retained 82 distributions. Only pypdf and urllib3 version/hash entries changed; other package versions and hashes are unchanged. The uv lock changes the same two external package identities and intended project constraint metadata. Refreshed dependency comments do not change additional package identities. The reviewed native-lock SHA is `70cf9a3661acea3fd856e5875dc77f4749fa4271aacd5dd575c72d75c99cea20`.

Independent review matched wheel and source hashes to official [pypdf 6.19.0 metadata](https://pypi.org/pypi/pypdf/6.19.0/json) and [urllib3 2.8.0 metadata](https://pypi.org/pypi/urllib3/2.8.0/json). Their Python requirements include the project's Python 3.12 runtime; the resolver accepts the updated urllib3 with botocore. The PyAV wheel policy is preserved.

The coder ran 53 affected native-payload/pack and agenda-PDF tests successfully in 2.24 seconds, plus lock, Ruff and diff checks. The existing hosted manual bytes passed currentness checking under pypdf 6.19.0; no fresh render was substituted. The independent reviewer checked the two-package resolver delta, reviewed lock hash, official artifact hashes, compatibility and three lock assertions, all passing. Caption code, model pins and station controls are unchanged.

The earlier combined affected suite passed 480 tests before this two-package change. Final artifacts must be built from the corrected source and bind to that exact commit; earlier candidate installer/runtime packs are not final release evidence. Inherited repository-wide Ruff findings (113 findings across 19 unchanged files) and other development-dependency CI advisories are not represented as green or resolved by these two fixes.

No local native build, model load, service restart, Sandbox or publication was performed.

proved: 53 affected tests passed; independent two-package/hash/compatibility review passed; lock and staged-manual checks passed | lane: Critical
