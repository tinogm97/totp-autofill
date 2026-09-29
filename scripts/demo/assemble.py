"""Monta el vídeo: rótulos, escenas con subtítulo, transiciones y GIF.

Uso: assemble.py DIR_ESCENAS DIR_SALIDA
Genera demo.mp4, demo-poster.png y demo.gif en DIR_SALIDA.
"""

import json
import subprocess
import sys
from pathlib import Path

FONT = "/usr/share/fonts/truetype/ubuntu/Ubuntu-M.ttf"
FADE = 0.6
SCENES = [
    ("1-app", "Tus cuentas 2FA, con los secretos en el llavero del sistema"),
    ("2-import", "Importa todas tus cuentas de Google Authenticator con la webcam"),
    ("3-auto", "Inicia sesión como siempre: el código se escribe solo"),
    ("4-picker", "¿Sitio nuevo? Eliges la cuenta una vez y la recuerda", "top"),
    ("5-shortcut", "En cualquier aplicación: Ctrl + Alt + 2"),
]


def run(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return float(json.loads(out.stdout)["format"]["duration"])


def main(src: Path, dst: Path) -> None:
    clips: list[Path] = []

    for card, seconds in (("intro", 3.6), ("outro", 5.0)):
        run("-loop", "1", "-t", str(seconds), "-i", str(src / f"{card}.png"),
            "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-crf", "18",
            str(src / f"{card}.mp4"))

    clips.append(src / "intro.mp4")
    for name, caption, *where in SCENES:
        y = "118" if where == ["top"] else "h-text_h-44"  # "top": bajo la barra de Chrome
        text_file = src / f"{name}.txt"
        text_file.write_text(caption, encoding="utf-8")
        captioned = src / f"{name}-c.mp4"
        drawtext = (f"drawtext=fontfile={FONT}:textfile={text_file}:fontsize=30:"
                    "fontcolor=white:box=1:boxcolor=0x0f1424@0.86:boxborderw=20:"
                    f"x=(w-text_w)/2:y={y}:alpha='min(1,max(0,(t-0.3)/0.5))'")
        run("-i", str(src / f"{name}.mp4"), "-vf", f"fps=30,{drawtext},format=yuv420p",
            "-c:v", "libx264", "-crf", "18", str(captioned))
        clips.append(captioned)
    clips.append(src / "outro.mp4")

    # Transiciones: cada clip entra con un fundido sobre el anterior.
    inputs = [arg for clip in clips for arg in ("-i", str(clip))]
    durations = [duration(c) for c in clips]
    chain, offset, last = [], 0.0, "0:v"
    for i in range(1, len(clips)):
        offset += durations[i - 1] - FADE
        out = f"v{i}"
        chain.append(f"[{last}][{i}:v]xfade=transition=fade:duration={FADE}:offset={offset:.3f}[{out}]")
        last = out
    total = sum(durations) - FADE * (len(clips) - 1)
    chain.append(f"[{last}]fade=t=in:st=0:d=0.5,fade=t=out:st={total - 0.7:.3f}:d=0.7,"
                 "format=yuv420p[final]")
    video = dst / "demo.mp4"
    run(*inputs, "-filter_complex", ";".join(chain), "-map", "[final]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "24", "-movflags", "+faststart",
        str(video))

    # Póster (escena del relleno automático) y GIF corto para el README.
    auto = src / "3-auto-c.mp4"
    run("-sseof", "-1.2", "-i", str(auto), "-frames:v", "1", str(dst / "demo-poster.png"))
    run("-i", str(auto), "-vf",
        "fps=12,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];"
        "[b][p]paletteuse=dither=bayer:bayer_scale=4", str(dst / "demo.gif"))
    print(f"{video}: {total:.1f} s, {video.stat().st_size / 1e6:.1f} MB; "
          f"demo.gif {(dst / 'demo.gif').stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
