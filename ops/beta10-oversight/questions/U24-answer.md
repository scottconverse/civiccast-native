# U24 - coordinator audit: the in-place trim is broken; fix it (2026-09-25 MDT)

## Finding (coordinator, OBSERVED, reproducible)
`_trim_relay_log`'s docstring says "measured on Windows: append-mode ffmpeg writes after a rewrite continue from
the new size". They do not. Reproduction: `evidence\u24-trim-hole\trimtest.py`, run with this worktree's venv and
the real `civiccast.stream._ffmpeg.start_ffmpeg(args, stderr_path=p)` (ffmpeg 8.1.1, `-loglevel debug`, lavfi sine,
12 s). After 5 s the file is rewritten in place ("wb", header + 2000-byte tail), exactly as `_trim_relay_log` does:

```
before 5663 after_trim 2007 1s later 5809 final 5882 NULs 3656 first_nul_at 2007
```

The child's handle keeps its own file position (the CRT's O_APPEND emulation lives in the parent process, not in
the OS handle the child inherits), so its next write lands at its old offset and the gap is zero-filled. Result:
the file size equals the child's total bytes ever written, so the cap bounds nothing. It trims every tick
(WARNING spam every tick once over the cap), and the retained content is mostly NULs. Any test that "proved" the
cap used a fake writer in-process, not the real inherited handle across a rewrite. Find and name the test or
measurement that supported the docstring claim, and say why it passed.

## Decision (engineering): the parent owns the file
Replace "child writes the file directly + parent trims in place" with:
- ffmpeg stderr = `subprocess.PIPE`;
- one daemon drain thread per relay child that reads the pipe continuously (read in chunks; never blocks on
  anything but the read and a local file write), and writes to the per-channel log file it OWNS: header at spawn,
  then lines; when the file passes the cap, the THREAD rotates/trims (it holds the only handle, so a rewrite or
  rename is safe);
- on any write error the thread keeps draining and discards (the relay must never stall on its log); it logs one
  WARNING per episode;
- the thread ends at EOF of the pipe (child exit); it must not keep the relay object alive or block `terminate()`;
- keep the header format, the path, the cap numbers, spawn rotation, and the no-restart-on-trim property.

## Proof required
1. Red: your cap test, converted to use a REAL ffmpeg child through the real starter, must fail on `3ad288ed`
   (NULs present / file larger than cap after the child writes past a trim). Green after.
2. A stall test: a real ffmpeg with `-loglevel debug` writing well over 1 MiB of stderr (e.g. 60 s of a verbose
   lavfi input with `-f null -`) finishes in wall time within +10 % of the same run with stderr to DEVNULL, and the
   log is <= cap with no NUL bytes.
3. Thread lifecycle: after the child exits the thread has ended (join with timeout in the test); terminate() of a
   relay is not slowed by the thread.
4. Gates as before. Small commits, never amend.
5. Then RE-STAGE `staging\U24\` (rebuild candidate/overlay/patches/proofs 1-5 with the new commits; say what
   changed versus the first staging).

Also: never again size a test's write from a constant that a mutation can change; keep scratch writes under
`%TEMP%\u24` and delete them. Report the disk-free figure before and after.
