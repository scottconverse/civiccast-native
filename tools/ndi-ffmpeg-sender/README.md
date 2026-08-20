# CivicCast NDI FFmpeg Sender

Internal lab tool for public-access-station NDI testing.

This executable launches FFmpeg, reads BGRA rawvideo frames from FFmpeg stdout,
and publishes those frames as an NDI source through the local NDI runtime.

It is deliberately not a public release artifact. NDI SDK/runtime licensing is
handled by the workstation where the test is run.

## Build

```powershell
cd tools\ndi-ffmpeg-sender
cargo build --release
```

If Windows cannot find the NDI runtime DLL, copy `Processing.NDI.Lib.x64.dll`
next to `target\release\civiccast-ndi-ffmpeg-sender.exe` or add the installed
NDI Runtime directory to `PATH`.

## Send a test pattern

```powershell
target\release\civiccast-ndi-ffmpeg-sender.exe --name "CivicCast Lab Proof" --duration-seconds 30
```

Open NDI Studio Monitor and select the `CivicCast Lab Proof` source.

## Send a media file

```powershell
target\release\civiccast-ndi-ffmpeg-sender.exe --input C:\path\to\sample.mp4 --name "CivicCast Meeting Proof"
```
