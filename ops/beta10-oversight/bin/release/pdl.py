import concurrent.futures as cf
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from pathlib import Path

CH = 64 * 1024 * 1024
W = 16


def executable(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise FileNotFoundError(f"required command {name!r} was not found on PATH")
    return path


class HTTPSOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme.lower() != "https":
            raise urllib.error.URLError("artifact redirect must remain HTTPS")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


https_opener = urllib.request.build_opener(HTTPSOnlyRedirectHandler)


def _curl_config_quote(value: str) -> str:
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError("GitHub token contains a control character")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def fresh_url(artifact_id: str):
    if not artifact_id.isdecimal():
        raise ValueError("artifact id must contain only decimal digits")
    token = subprocess.check_output(  # noqa: S603
        [executable("gh"), "auth", "token"], text=True, shell=False
    )
    token = token.strip()
    if not token:
        raise ValueError("gh auth token returned an empty token")
    # curl reads the credential on stdin, keeping it out of process argv.
    config = (
        f"header = {_curl_config_quote(f'Authorization: Bearer {token}')}\n"
        f"header = {_curl_config_quote('Accept: application/vnd.github+json')}\n"
    )
    result = subprocess.run(  # noqa: S603
        [
            executable("curl"),
            "-s",
            "--fail",
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
            "-o",
            "NUL",
            "-w",
            "%{redirect_url}",
            "--config",
            "-",
            f"https://api.github.com/repos/scottconverse/civiccast-native/actions/artifacts/{artifact_id}/zip",
        ],
        input=config,
        capture_output=True,
        text=True,
        shell=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl could not resolve artifact {artifact_id}")
    return result.stdout.strip()


def artifact_range_request(download_url: str, start: int, end: int) -> urllib.request.Request:
    parsed = urllib.parse.urlsplit(download_url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("artifact redirect must use HTTPS")
    # This is a fresh request to the signed storage URL. It never inherits
    # the Authorization header used to discover that URL from GitHub.
    return urllib.request.Request(  # noqa: S310 - validated HTTPS signed URL.
        download_url, headers={"Range": f"bytes={start}-{end}"}
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 4:
        raise SystemExit("usage: pdl.py <unused-url-file> <output-file> <size-bytes> <artifact-id>")
    _, out, size_text, artifact_id = args
    try:
        size = int(size_text)
    except ValueError as exc:
        raise SystemExit("size-bytes must be a positive integer") from exc
    if size <= 0:
        raise SystemExit("size-bytes must be a positive integer")

    url = [fresh_url(artifact_id)]
    artifact_range_request(url[0], 0, min(size - 1, CH - 1))
    lock = threading.Lock()
    done = [0]
    output = Path(out)
    with output.open("wb") as f:
        f.truncate(size)

    def get(i: int) -> None:
        s = i * CH
        e = min(size - 1, s + CH - 1)
        for attempt in range(8):
            try:
                download_url = url[0]
                request = artifact_range_request(download_url, s, e)
                # The fresh request has only Range; HTTPSOnlyRedirectHandler
                # rejects every downgrade if storage redirects again.
                with https_opener.open(request, timeout=120) as response:
                    data = response.read()
                if len(data) != e - s + 1:
                    raise OSError("short")
                with lock:
                    with output.open("r+b") as f:
                        f.seek(s)
                        f.write(data)
                    done[0] += len(data)
                return
            except Exception:
                if attempt == 3:
                    with lock:
                        url[0] = fresh_url(artifact_id)
                time.sleep(2 + attempt * 3)
        raise SystemExit(f"chunk {i} failed")

    n = (size + CH - 1) // CH
    started = time.time()

    def progress() -> None:
        while done[0] < size:
            time.sleep(60)
            elapsed = time.time() - started
            print(
                f"{time.strftime('%H:%M:%S')} {done[0] / 1e9:.2f}/{size / 1e9:.2f} GB "
                f"{done[0] / 1e6 / elapsed:.1f} MB/s",
                flush=True,
            )

    threading.Thread(target=progress, daemon=True).start()
    with cf.ThreadPoolExecutor(W) as executor:
        list(executor.map(get, range(n)))
    print("PDL DONE", time.strftime("%H:%M:%S"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
