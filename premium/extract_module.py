#!/usr/bin/env python3
"""
프리미엄 모듈에서 번역 대상 텍스트를 추출하는 스크립트.

NWM/HAK 파일에서 GFF 리소스(.dlg, .utc, .uti, .utp, .jrl 등)를 추출하고,
CExoLocString 인라인 텍스트를 CSV로 내보낸다.
커스텀 TLK가 있는 경우 TLK → CSV 추출도 수행한다.

GFF 헤더의 실제 타입을 기준으로 분류한다 (ERF 타입 ID와 무관).
GIT 파일의 인라인 크리처/배치물 인스턴스도 추출한다.

사용법:
    python3 premium/extract_module.py dod          # 단일 모듈 추출
    python3 premium/extract_module.py --all         # 전체 모듈 추출
    python3 premium/extract_module.py dod --stats   # 통계만 출력
"""

import csv
import importlib
import struct
import sys
from pathlib import Path
from collections import defaultdict

# 프로젝트 루트를 path에 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from gff_tool import GffFile, CExoLocString, CEXOLOCSTRING, STRUCT, LIST
from analyze_premium_modules import read_erf_entries, read_resource_data, RES_TYPES

NWN_BASE = Path.home() / "Library/Application Support/Steam/steamapps/common/Neverwinter Nights"
NWM_DIR = NWN_BASE / "data" / "nwm"
MOD_DIR = NWN_BASE / "data" / "mod"
HAK_DIR = NWN_BASE / "data" / "hk"
TLK_DIR = NWN_BASE / "data" / "tlk"

# GFF 헤더 타입 → 확장자 매핑
GFF_HEADER_TO_EXT = {
    "UTC": "utc",
    "DLG": "dlg",
    "UTI": "uti",
    "UTP": "utp",
    "UTT": "utt",
    "UTD": "utd",
    "UTM": "utm",
    "UTE": "ute",
    "UTS": "uts",
    "JRL": "jrl",
    "IFO": "ifo",
    "GFF": "gff",
    "GIT": "git",
}


def load_module_config(module_name: str) -> dict:
    """모듈 config.py 로드"""
    config_path = Path(__file__).parent / module_name / "config.py"
    if not config_path.exists():
        print(f"Error: {config_path} not found")
        sys.exit(1)

    spec = importlib.util.spec_from_file_location("config", config_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.MODULE


def get_module_path(config: dict) -> Path:
    """모듈 파일(.nwm 또는 .mod) 경로 반환"""
    if "nwm" in config:
        return NWM_DIR / config["nwm"]
    elif "mod" in config:
        return MOD_DIR / config["mod"]
    return None


def get_hak_paths(config: dict) -> list[Path]:
    """HAK 파일 경로 목록 반환"""
    paths = []
    for hak_name in config.get("hak", []):
        hak_path = HAK_DIR / f"{hak_name}.hak"
        if hak_path.exists():
            paths.append(hak_path)
        else:
            print(f"  Warning: HAK not found: {hak_path}")
    return paths


def extract_locstrings_from_struct(gff_struct, path_prefix=""):
    """GFF 구조체에서 CExoLocString 필드를 재귀적으로 추출.

    Returns: list of (field_path, CExoLocString)
    """
    results = []

    for label, (field_type, value) in gff_struct.fields.items():
        field_path = f"{path_prefix}/{label}" if path_prefix else label

        if field_type == CEXOLOCSTRING and isinstance(value, CExoLocString):
            if value.substrings:
                results.append((field_path, value))
            elif value.strref not in (-1, 0xFFFFFFFF):
                results.append((field_path, value))

        elif field_type == STRUCT:
            results.extend(extract_locstrings_from_struct(value, field_path))

        elif field_type == LIST and isinstance(value, list):
            for i, item in enumerate(value):
                results.extend(
                    extract_locstrings_from_struct(item, f"{field_path}/{i}")
                )

    return results


def read_gff_header(data: bytes) -> str | None:
    """GFF 데이터의 헤더 타입 읽기 (예: 'UTC', 'DLG', 'GIT')"""
    if len(data) < 14:
        return None
    try:
        header = data[0:4].decode('ascii', errors='replace').strip('\x00').strip()
        version = data[4:8].decode('ascii', errors='replace').strip('\x00').strip()
        if version == 'V3.2':
            return header
    except:
        pass
    return None


def extract_from_erf(erf_path: Path, stats_only: bool = False):
    """ERF 파일에서 GFF 리소스의 인라인 텍스트 추출.

    GFF 헤더의 실제 타입을 기준으로 분류한다.
    GIT 파일의 Creature List / Placeable List도 스캔한다.

    Returns: list of row dicts, type_stats dict
    """
    file_type, file_version, entries = read_erf_entries(erf_path)
    if file_type is None:
        return [], {}

    rows = []
    type_stats = defaultdict(int)

    gff_count = 0

    for resref, res_type, res_id, offset, size in entries:
        if size < 14:
            continue

        data = read_resource_data(erf_path, offset, size)
        gff_type = read_gff_header(data)
        if gff_type is None:
            continue

        ext = GFF_HEADER_TO_EXT.get(gff_type)
        if ext is None:
            continue

        gff_count += 1
        type_stats[ext] += 1

        if stats_only:
            continue

        try:
            gff = GffFile.from_bytes(data)
        except Exception as e:
            print(f"    Warning: Failed to parse {resref}.{ext}: {e}")
            continue

        locstrings = extract_locstrings_from_struct(gff.root)

        for field_path, locstr in locstrings:
            if locstr.substrings:
                for lang_id, text in locstr.substrings.items():
                    if text.strip():
                        rows.append({
                            "Resource": resref,
                            "ResType": ext,
                            "FieldPath": field_path,
                            "LangID": lang_id,
                            "StrRef": locstr.strref,
                            "Text": text,
                        })

    print(f"  {erf_path.name}: {len(entries)} resources, {gff_count} GFF files")

    return rows, type_stats


def extract_custom_tlk(config: dict, output_dir: Path):
    """커스텀 TLK 파일을 CSV로 추출"""
    tlk_name = config.get("custom_tlk")
    if not tlk_name:
        return

    tlk_path = TLK_DIR / f"{tlk_name}.tlk"
    if not tlk_path.exists():
        print(f"  Custom TLK not found: {tlk_path}")
        return

    output_csv = output_dir / f"{tlk_name}.csv"
    print(f"\n  Extracting custom TLK: {tlk_path.name}")

    from tlk_to_csv import TLKParser
    parser = TLKParser(tlk_path, encoding='auto')
    entries = parser.parse()
    parser.to_csv(output_csv)

    non_empty = sum(1 for e in entries if e.text.strip())
    print(f"  → {output_csv.name}: {len(entries)} entries ({non_empty} non-empty)")


def extract_module(module_name: str, stats_only: bool = False, preserve: bool = False):
    """단일 모듈에서 텍스트 추출"""
    config = load_module_config(module_name)
    print(f"\n{'='*60}")
    print(f"Module: {config['name']} ({module_name})")
    print(f"{'='*60}")

    if config.get("installed") is False:
        print("  [SKIP] 미설치 모듈")
        return

    module_dir = Path(__file__).parent / module_name
    tlk_dir = module_dir / "tlk"
    inline_dir = module_dir / "inline"
    tlk_dir.mkdir(parents=True, exist_ok=True)
    inline_dir.mkdir(parents=True, exist_ok=True)

    # 1. 커스텀 TLK 추출
    extract_custom_tlk(config, tlk_dir)

    # 2. NWM/MOD에서 인라인 텍스트 추출
    module_path = get_module_path(config)
    all_rows = []
    all_type_stats = defaultdict(int)

    if module_path and module_path.exists():
        print(f"\n  Extracting from: {module_path.name}")
        rows, type_stats = extract_from_erf(module_path, stats_only)
        all_rows.extend(rows)
        for k, v in type_stats.items():
            all_type_stats[k] += v
    elif module_path:
        print(f"  Module file not found: {module_path}")

    # 3. HAK 파일에서 인라인 텍스트 추출
    hak_paths = get_hak_paths(config)
    for hak_path in hak_paths:
        print(f"\n  Extracting from HAK: {hak_path.name}")
        rows, type_stats = extract_from_erf(hak_path, stats_only)
        all_rows.extend(rows)
        for k, v in type_stats.items():
            all_type_stats[k] += v

    # 통계 출력
    print(f"\n  --- Resource stats ---")
    for ext, count in sorted(all_type_stats.items()):
        print(f"    .{ext}: {count} files")

    if stats_only:
        return

    if not all_rows:
        print(f"\n  No inline text found")
        return

    # 4. 인라인 텍스트를 리소스 타입별로 CSV 저장
    rows_by_type = defaultdict(list)
    for row in all_rows:
        rows_by_type[row["ResType"]].append(row)

    fieldnames = ["Resource", "ResType", "FieldPath", "LangID", "StrRef", "TextEng", "Text"]

    for res_type, rows in sorted(rows_by_type.items()):
        rows.sort(key=lambda r: (r["Resource"], r["FieldPath"], r["LangID"]))

        csv_path = inline_dir / f"{res_type}.csv"

        # 기존 번역 보존: 기존 CSV에서 Text 컬럼을 읽어 매칭
        existing_translations = {}
        if preserve and csv_path.exists():
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for erow in reader:
                    text = erow.get("Text", "").strip()
                    if text:
                        key = (erow["Resource"], erow["FieldPath"], erow.get("LangID", "0"))
                        existing_translations[key] = text
            if existing_translations:
                print(f"    (preserving {len(existing_translations)} existing translations)")

        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                row["TextEng"] = row.pop("Text")
                key = (row["Resource"], row["FieldPath"], str(row["LangID"]))
                row["Text"] = existing_translations.get(key, "")
                writer.writerow(row)

        print(f"  → {csv_path.relative_to(Path(__file__).parent)}: {len(rows)} entries")

    total = sum(len(r) for r in rows_by_type.values())
    print(f"\n  Total inline text entries: {total}")


def list_modules() -> list[str]:
    """사용 가능한 모듈 목록 반환"""
    premium_dir = Path(__file__).parent
    modules = []
    for d in sorted(premium_dir.iterdir()):
        if d.is_dir() and (d / "config.py").exists():
            modules.append(d.name)
    return modules


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="프리미엄 모듈에서 번역 대상 텍스트 추출"
    )
    parser.add_argument(
        "module", nargs="?",
        help="모듈 디렉토리명 (예: dod, totms, wcoc)"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="전체 모듈 추출"
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="통계만 출력 (CSV 생성 안함)"
    )
    parser.add_argument(
        "--preserve", action="store_true",
        help="기존 번역(Text 컬럼) 보존"
    )
    parser.add_argument(
        "--list", action="store_true",
        help="사용 가능한 모듈 목록 출력"
    )

    args = parser.parse_args()

    if args.list:
        print("Available modules:")
        for m in list_modules():
            config = load_module_config(m)
            installed = config.get("installed", True)
            status = "" if installed else " [미설치]"
            print(f"  {m:20s} — {config['name']}{status}")
        return

    if args.all:
        for module_name in list_modules():
            extract_module(module_name, stats_only=args.stats, preserve=args.preserve)
    elif args.module:
        extract_module(args.module, stats_only=args.stats, preserve=args.preserve)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
