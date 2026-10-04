# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
import concurrent.futures as cf
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

url_file, out, size = sys.argv[1], sys.argv[2], int(sys.argv[3])
CH = 64 * 1024 * 1024
W = 16


def _tool(name):
    # Local operator tooling comes from their PATH, never artifact/evidence data.
    found = shutil.which(name)
    if found is None:
        raise RuntimeError(f"required local tool unavailable: {name}")
    return str(Path(found).resolve())


def _https_url(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or any(ord(char) <= 32 for char in value)
    ):
        raise ValueError("artifact download requires an HTTPS URL without credentials")
    return value


class _HTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _https_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fresh_url():
    artifact = sys.argv[4]
    if not artifact.isascii() or not artifact.isdecimal():
        raise ValueError("artifact ID must contain only ASCII digits")
    try:
        # Explicit resolved local CLI; fixed argv, no shell or credential argument.
        tok = subprocess.check_output(  # noqa: S603
            [_tool("gh"), "auth", "token"], text=True, stderr=subprocess.PIPE, timeout=30
        ).strip()
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("GitHub CLI authentication unavailable") from None
    if not tok or any(char.isspace() for char in tok):
        raise RuntimeError("GitHub CLI returned an invalid authentication token")
    try:
        r = subprocess.run(  # noqa: S603 -- resolved local curl, fixed API URL, no shell
            [
                _tool("curl"),
                "-q",  # Disable curlrc: it could enable credential-bearing traces.
                "-s",
                "--fail",
                "--proto",
                "=https",
                "-o",
                "NUL",
                "-w",
                "%{redirect_url}",
                "-H",
                "@-",  # Header stdin keeps the token out of process command lines.
                "-H",
                "Accept: application/vnd.github+json",
                "https://api.github.com/repos/scottconverse/civiccast-native/actions/artifacts/"
                + artifact
                + "/zip",
            ],
            input=f"Authorization: Bearer {tok}\n",
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("GitHub artifact redirect request failed") from None
    if r.returncode:
        # Never expose captured stderr/exception details from an authenticated call.
        raise RuntimeError("GitHub artifact redirect request failed")
    return _https_url(r.stdout.strip())


url = [fresh_url()]
lock = threading.Lock()
done = [0]
with Path(out).open("wb") as f:
    f.truncate(size)


def get(i):
    s = i * CH
    e = min(size - 1, s + CH - 1)
    for a in range(8):
        try:
            rq = urllib.request.Request(  # noqa: S310 -- URL and every redirect are HTTPS-only
                _https_url(url[0]), headers={"Range": f"bytes={s}-{e}"}
            )
            with urllib.request.build_opener(_HTTPSRedirectHandler()).open(
                rq, timeout=120
            ) as response:
                d = response.read()
            if len(d) != e - s + 1:
                raise OSError("short")
            with lock:
                with Path(out).open("r+b") as f:
                    f.seek(s)
                    f.write(d)
                done[0] += len(d)
            return
        except Exception:
            if a == 3:
                with lock:
                    url[0] = fresh_url()
            time.sleep(2 + a * 3)
    raise SystemExit(f"chunk {i} failed")


n = (size + CH - 1) // CH
t0 = time.time()


def prog():
    while done[0] < size:
        time.sleep(60)
        print(
            f"{time.strftime('%H:%M:%S')} {done[0] / 1e9:.2f}/{size / 1e9:.2f} GB "
            f"{done[0] / 1e6 / (time.time() - t0):.1f} MB/s",
            flush=True,
        )


threading.Thread(target=prog, daemon=True).start()
with cf.ThreadPoolExecutor(W) as ex:
    list(ex.map(get, range(n)))
print("PDL DONE", time.strftime("%H:%M:%S"), flush=True)
