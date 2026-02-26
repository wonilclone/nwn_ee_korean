#!/usr/bin/env python3
"""
output/ 하위의 모든 TGA 포트레이트를 release/portraits/ 에 flat하게 모은다.

사용법:
  python3 collect_portraits.py              # 기본 경로
  python3 collect_portraits.py -o ../release/portraits  # 출력 디렉토리 지정
"""

import argparse
import shutil
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="포트레이트 TGA를 릴리스 디렉토리에 수집")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="출력 디렉토리 (기본: <프로젝트>/release/portraits/)")
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    source_dir = script_dir / "output"
    dest_dir = args.output or project_root / "release" / "portraits"

    if not source_dir.is_dir():
        print(f"Error: output 디렉토리를 찾을 수 없습니다: {source_dir}")
        sys.exit(1)

    dest_dir.mkdir(parents=True, exist_ok=True)

    tga_files = sorted(source_dir.rglob("*.tga"))
    if not tga_files:
        print("복사할 TGA 파일이 없습니다.")
        sys.exit(0)

    for tga in tga_files:
        shutil.copy2(tga, dest_dir / tga.name)

    print(f"{len(tga_files)}개 TGA → {dest_dir}/")


if __name__ == "__main__":
    main()
