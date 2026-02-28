#!/usr/bin/env python3
"""
NWN:EE 포트레이트 생성 스크립트
source/ 의 이미지(png, jpg 등)를 NWN:EE 포트레이트 규격 TGA로 변환하여 output/ 에 저장한다.

출력 규격 (모두 1:2 비율):
  _h.tga  256x512
  _l.tga  128x256
  _m.tga   64x128
  _s.tga   32x64
  _t.tga   16x32

소스 이미지가 1:2 비율이 아닌 경우, 좌상단(0,0)을 기준으로 크롭한다.
- 너무 넓으면 → 오른쪽을 자름 (width = height / 2)
- 너무 높으면 → 아래를 자름 (height = width * 2)
"""

import argparse
import os
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow 라이브러리가 필요합니다. 설치: pip install Pillow")
    sys.exit(1)

SIZES = [
    ("h", 256, 512),
    ("l", 128, 256),
    ("m", 64, 128),
    ("s", 32, 64),
    ("t", 16, 32),
]

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".webp", ".tiff", ".tif"}


BOTTOM_PADDING_RATIO = 112 / 512  # 샘플 기준: 하단 ~21.9%를 단색 빈 영역으로


def crop_to_content_ratio(img: Image.Image) -> Image.Image:
    """컨텐츠 영역 비율로 크롭. 좌상단(0,0) 기준.
    최종 출력은 1:2 비율이고, 하단 패딩을 제외한 컨텐츠 영역은 1:1.5625 비율."""
    w, h = img.size
    content_ratio = 1 / (2 * (1 - BOTTOM_PADDING_RATIO))  # 컨텐츠 w:h 비율
    target_w = round(h * content_ratio)
    target_h = round(w / content_ratio)

    if w - target_w > 1:
        img = img.crop((0, 0, target_w, h))
    elif h - target_h > 1:
        img = img.crop((0, 0, w, target_h))

    return img


def shrink_sources(sources: list[Path], max_height: int) -> None:
    """소스 이미지를 컨텐츠 비율로 크롭하고 max_height 이하로 리사이즈하여 덮어쓴다."""
    targets = []
    for src in sources:
        if not src.is_file():
            continue
        img = Image.open(src)
        cropped = crop_to_content_ratio(img)
        needs_crop = cropped.size != img.size
        needs_resize = cropped.height > max_height
        if needs_crop or needs_resize:
            targets.append((src, img.size))

    if not targets:
        print(f"처리할 소스가 없습니다. (모두 비율 일치, {max_height}px 이하)")
        return

    print(f"소스 정리: {len(targets)}개 (크롭 + 최대 높이 {max_height}px)")
    print()

    for src, (ow, oh) in targets:
        img = Image.open(src).convert("RGB")
        img = crop_to_content_ratio(img)
        cw, ch = img.size
        if ch > max_height:
            ratio = max_height / ch
            img = img.resize((round(cw * ratio), max_height), Image.LANCZOS)
        nw, nh = img.size
        img.save(src)
        print(f"  {src.name}: {ow}x{oh} → {nw}x{nh}")

    print()
    print("완료!")


def generate_portrait(src_path: Path, output_dir: Path) -> None:
    """하나의 소스 이미지에서 5개 TGA 포트레이트를 생성한다."""
    name = src_path.stem
    dest_dir = output_dir / name
    dest_dir.mkdir(parents=True, exist_ok=True)

    img = Image.open(src_path).convert("RGB")
    original_size = img.size

    img = crop_to_content_ratio(img)
    cropped_size = img.size

    if original_size != cropped_size:
        print(f"  {name}: {original_size[0]}x{original_size[1]} → 크롭 {cropped_size[0]}x{cropped_size[1]}")
    else:
        print(f"  {name}: {original_size[0]}x{original_size[1]}")

    for suffix, w, h in SIZES:
        content_h = round(h * (1 - BOTTOM_PADDING_RATIO))
        canvas = Image.new("RGB", (w, h), (0, 0, 0))
        resized = img.resize((w, content_h), Image.LANCZOS)
        canvas.paste(resized, (0, 0))
        out_path = dest_dir / f"{name}_{suffix}.tga"
        canvas.save(out_path)

    print(f"    → {dest_dir}/")


def main():
    parser = argparse.ArgumentParser(description="NWN:EE 포트레이트 생성")
    parser.add_argument("--source", default=None, help="소스 디렉토리 (기본: portraits/source/)")
    parser.add_argument("--output", default=None, help="출력 디렉토리 (기본: portraits/output/)")
    parser.add_argument("--all", action="store_true", help="이미 존재하는 포트레이트도 재생성")
    parser.add_argument("--shrink-source", type=int, metavar="MAX_HEIGHT", nargs="?", const=1024,
                        help="소스 이미지를 MAX_HEIGHT 이하로 리사이즈 (기본: 1024, 포트레이트 생성 안함)")
    parser.add_argument("files", nargs="*", help="특정 파일만 처리 (미지정시 전체)")
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    source_dir = Path(args.source) if args.source else script_dir / "source"
    output_dir = Path(args.output) if args.output else script_dir / "output"

    if not source_dir.is_dir():
        print(f"Error: 소스 디렉토리를 찾을 수 없습니다: {source_dir}")
        sys.exit(1)

    if args.files:
        sources = [Path(f) for f in args.files]
    else:
        sources = sorted(
            f for f in source_dir.iterdir()
            if f.suffix.lower() in SUPPORTED_EXTENSIONS
        )

    if args.shrink_source is not None:
        shrink_sources(sources, args.shrink_source)
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    if not args.files and not args.all:
        sources = [
            s for s in sources
            if not (output_dir / s.stem / f"{s.stem}_h.tga").exists()
        ]

    if not sources:
        print("처리할 소스 이미지가 없습니다. (전체 재생성: --all)")
        sys.exit(0)

    print(f"포트레이트 생성: {len(sources)}개 이미지")
    print()

    for src in sources:
        if not src.is_file():
            print(f"  경고: 파일을 찾을 수 없습니다: {src}")
            continue
        generate_portrait(src, output_dir)

    print()
    print("완료!")


if __name__ == "__main__":
    main()
