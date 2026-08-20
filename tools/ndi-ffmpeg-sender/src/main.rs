use ndi::{send::SendBuilder, FourCCVideoType, FrameFormatType, VideoData};
use std::{
    env,
    io::{self, Read},
    path::PathBuf,
    process::{Command, Stdio},
};

#[derive(Debug)]
struct Config {
    ffmpeg: String,
    input: Option<PathBuf>,
    name: String,
    width: i32,
    height: i32,
    fps_num: i32,
    fps_den: i32,
    duration_seconds: u32,
}

fn usage() -> &'static str {
    "Usage: civiccast-ndi-ffmpeg-sender [--input FILE] [--name NAME] [--width N] [--height N] [--fps N] [--duration-seconds N] [--ffmpeg PATH]"
}

fn parse_args() -> Result<Config, String> {
    let mut config = Config {
        ffmpeg: "ffmpeg".to_string(),
        input: None,
        name: "CivicCast Lab Proof".to_string(),
        width: 1280,
        height: 720,
        fps_num: 30,
        fps_den: 1,
        duration_seconds: 30,
    };

    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        let value = |args: &mut std::iter::Skip<std::env::Args>, flag: &str| {
            args.next()
                .ok_or_else(|| format!("{flag} needs a value.\n{}", usage()))
        };
        match arg.as_str() {
            "--help" | "-h" => {
                println!("{}", usage());
                std::process::exit(0);
            }
            "--ffmpeg" => config.ffmpeg = value(&mut args, "--ffmpeg")?,
            "--input" => config.input = Some(PathBuf::from(value(&mut args, "--input")?)),
            "--name" => config.name = value(&mut args, "--name")?,
            "--width" => {
                config.width = value(&mut args, "--width")?
                    .parse()
                    .map_err(|_| "--width must be an integer".to_string())?
            }
            "--height" => {
                config.height = value(&mut args, "--height")?
                    .parse()
                    .map_err(|_| "--height must be an integer".to_string())?
            }
            "--fps" => {
                config.fps_num = value(&mut args, "--fps")?
                    .parse()
                    .map_err(|_| "--fps must be an integer".to_string())?
            }
            "--duration-seconds" => {
                config.duration_seconds = value(&mut args, "--duration-seconds")?
                    .parse()
                    .map_err(|_| "--duration-seconds must be an integer".to_string())?
            }
            other => return Err(format!("Unknown argument: {other}\n{}", usage())),
        }
    }

    if config.width <= 0 || config.height <= 0 || config.width % 2 != 0 {
        return Err(
            "Width and height must be positive, and width must be even for NDI video.".into(),
        );
    }
    if config.fps_num <= 0 || config.duration_seconds == 0 {
        return Err("FPS and duration must be positive.".into());
    }
    if let Some(input) = &config.input {
        if !input.exists() {
            return Err(format!("Input media does not exist: {}", input.display()));
        }
    }
    Ok(config)
}

fn ffmpeg_args(config: &Config) -> Vec<String> {
    let size = format!("{}x{}", config.width, config.height);
    let fps = config.fps_num.to_string();
    let mut args = vec![
        "-hide_banner".to_string(),
        "-loglevel".to_string(),
        "warning".to_string(),
    ];
    if let Some(input) = &config.input {
        args.extend([
            "-stream_loop".to_string(),
            "-1".to_string(),
            "-re".to_string(),
            "-i".to_string(),
            input.display().to_string(),
            "-t".to_string(),
            config.duration_seconds.to_string(),
            "-an".to_string(),
            "-vf".to_string(),
            format!("scale={size},fps={fps},format=bgra"),
        ]);
    } else {
        args.extend([
            "-re".to_string(),
            "-f".to_string(),
            "lavfi".to_string(),
            "-i".to_string(),
            format!("testsrc2=size={size}:rate={fps}"),
            "-t".to_string(),
            config.duration_seconds.to_string(),
            "-an".to_string(),
            "-vf".to_string(),
            "format=bgra".to_string(),
        ]);
    }
    args.extend([
        "-f".to_string(),
        "rawvideo".to_string(),
        "-pix_fmt".to_string(),
        "bgra".to_string(),
        "pipe:1".to_string(),
    ]);
    args
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let config =
        parse_args().map_err(|message| io::Error::new(io::ErrorKind::InvalidInput, message))?;
    ndi::initialize()
        .map_err(|_| io::Error::new(io::ErrorKind::Other, "NDI runtime initialization failed"))?;

    let sender = SendBuilder::new()
        .ndi_name(config.name.clone())
        .clock_video(true)
        .clock_audio(false)
        .build()
        .map_err(|_| io::Error::new(io::ErrorKind::Other, "NDI sender creation failed"))?;

    let args = ffmpeg_args(&config);
    eprintln!(
        "runtime=ffmpeg-rawvideo-to-ndi name=\"{}\" width={} height={} fps={}/{}",
        config.name, config.width, config.height, config.fps_num, config.fps_den
    );
    eprintln!("ffmpeg {} {}", config.ffmpeg, args.join(" "));

    let mut child = Command::new(&config.ffmpeg)
        .args(&args)
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()?;

    let mut stdout = child
        .stdout
        .take()
        .ok_or_else(|| io::Error::new(io::ErrorKind::Other, "FFmpeg stdout pipe unavailable"))?;
    let frame_size = (config.width * config.height * 4) as usize;
    let mut frame = vec![0_u8; frame_size];
    let mut frames_sent = 0_u64;

    loop {
        match stdout.read_exact(&mut frame) {
            Ok(()) => {
                let video = VideoData::from_buffer(
                    config.width,
                    config.height,
                    FourCCVideoType::BGRA,
                    config.fps_num,
                    config.fps_den,
                    FrameFormatType::Progressive,
                    0,
                    config.width * 4,
                    None,
                    &mut frame,
                );
                sender.send_video(&video);
                frames_sent += 1;
            }
            Err(error) if error.kind() == io::ErrorKind::UnexpectedEof => break,
            Err(error) => return Err(Box::new(error)),
        }
    }

    let status = child.wait()?;
    if !status.success() {
        return Err(format!("FFmpeg exited with status {status}").into());
    }
    eprintln!("ndi_sender_result=ok frames_sent={frames_sent}");
    unsafe { ndi::cleanup() };
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("error: {error}");
        std::process::exit(1);
    }
}
