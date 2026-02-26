#!/usr/bin/env python3
"""
영상에서 프레임을 추출하는 스크립트.
포트레이트 소스 이미지를 만들기 위해 mp4 등의 영상에서 지정한 프레임 레이트로 이미지를 뽑아낸다.

사용법:
  python3 extract_frames.py video.mp4                     # 기본 5fps로 추출
  python3 extract_frames.py video.mp4 --fps 10            # 10fps로 추출
  python3 extract_frames.py video.mp4 --start 30 --end 60 # 30초~60초 구간만
  python3 extract_frames.py video.mp4 -o my_frames/       # 출력 디렉토리 지정

필요: ffmpeg (brew install ffmpeg)
"""

import argparse
import subprocess
import sys
from pathlib import Path


def check_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except FileNotFoundError:
        print("Error: ffmpeg가 설치되어 있지 않습니다. 설치: brew install ffmpeg")
        sys.exit(1)


def extract_frames(video_path: Path, output_dir: Path, fps: float,
                   start: float | None, end: float | None, fmt: str):
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = video_path.stem
    pattern = str(output_dir / f"{stem}_%04d.{fmt}")

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning"]

    if start is not None:
        cmd += ["-ss", str(start)]
    cmd += ["-i", str(video_path)]
    if end is not None:
        duration = end - (start or 0)
        if duration > 0:
            cmd += ["-t", str(duration)]

    cmd += ["-vf", f"fps={fps}", "-y", pattern]

    print(f"영상: {video_path}")
    print(f"출력: {output_dir}/")
    print(f"프레임 레이트: {fps} fps")
    if start is not None or end is not None:
        s = start or 0
        e = f"{end}초" if end else "끝"
        print(f"구간: {s}초 ~ {e}")
    print()

    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("Error: ffmpeg 실행 실패")
        sys.exit(1)

    count = len(list(output_dir.glob(f"{stem}_*.{fmt}")))
    print(f"\n완료! {count}개 프레임 추출")


def main():
    parser = argparse.ArgumentParser(description="영상에서 프레임 추출")
    parser.add_argument("video", type=Path, help="입력 영상 파일 (mp4, avi, mkv 등)")
    parser.add_argument("--fps", type=float, default=5, help="추출 프레임 레이트 (기본: 5)")
    parser.add_argument("--start", type=float, default=None, help="시작 시간 (초)")
    parser.add_argument("--end", type=float, default=None, help="종료 시간 (초)")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="출력 디렉토리 (기본: ./frames_<영상이름>/)")
    parser.add_argument("--format", choices=["png", "jpg"], default="png",
                        help="출력 이미지 포맷 (기본: png)")
    args = parser.parse_args()

    if not args.video.is_file():
        print(f"Error: 파일을 찾을 수 없습니다: {args.video}")
        sys.exit(1)

    check_ffmpeg()

    output_dir = args.output or Path(f"frames_{args.video.stem}")
    extract_frames(args.video, output_dir, args.fps, args.start, args.end, args.format)


if __name__ == "__main__":
    main()
