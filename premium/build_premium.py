#!/usr/bin/env python3
"""
프리미엄 모듈 번역 빌드 스크립트.

번역된 CSV에서:
1. 커스텀 TLK 파일 빌드 (csv_to_tlk.py 활용)
2. GFF 파일에 인라인 텍스트 삽입 (gff_tool.py 활용)
3. 번역된 리소스로 모듈(.mod/.nwm) 재패킹

사용법:
    python3 premium/build_premium.py chess           # 단일 모듈 빌드
    python3 premium/build_premium.py --all            # 전체 모듈 빌드
    python3 premium/build_premium.py chess --release   # 빌드 + release 복사
"""

import csv
import importlib
import shutil
import struct
import sys
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from gff_tool import GffFile, CExoLocString, CEXOLOCSTRING, STRUCT, LIST
from csv_to_tlk import CSVToTLKConverter
from analyze_premium_modules import read_erf_entries, read_resource_data, RES_TYPES

NWN_BASE = Path.home() / "Library/Application Support/Steam/steamapps/common/Neverwinter Nights"
NWM_DIR = NWN_BASE / "data" / "nwm"
MOD_DIR = NWN_BASE / "data" / "mod"
HAK_DIR = NWN_BASE / "data" / "hk"
TLK_DIR = NWN_BASE / "data" / "tlk"

# GFF 헤더 타입 → 확장자 매핑 (ERF 타입 ID와 무관)
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
    if "nwm" in config:
        return NWM_DIR / config["nwm"]
    elif "mod" in config:
        return MOD_DIR / config["mod"]
    return None


def load_inline_translations(module_name: str) -> dict:
    """인라인 번역 CSV들을 로드.

    Returns: {(resref, res_type, field_path, lang_id): translated_text}
    """
    inline_dir = Path(__file__).parent / module_name / "inline"
    translations = {}

    if not inline_dir.exists():
        return translations

    for csv_path in sorted(inline_dir.glob("*.csv")):
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                text = row.get("Text", "").strip()
                if not text:
                    continue  # 미번역 항목 건너뛰기

                key = (
                    row["Resource"],
                    row["ResType"],
                    row["FieldPath"],
                    int(row["LangID"]),
                )
                translations[key] = text

    return translations


def set_locstring_in_struct(gff_struct, field_path: str, lang_id: int, text: str) -> bool:
    """GFF 구조체에서 field_path로 지정된 CExoLocString 필드에 텍스트 삽입."""
    parts = field_path.split("/")
    current = gff_struct

    for i, part in enumerate(parts[:-1]):
        if part.isdigit():
            idx = int(part)
            if isinstance(current, list) and idx < len(current):
                current = current[idx]
            else:
                return False
        else:
            if part not in current:
                return False
            field_type, value = current.fields[part]
            if field_type == LIST:
                current = value
            elif field_type == STRUCT:
                current = value
            else:
                return False

    final_label = parts[-1]
    if final_label not in current:
        return False

    field_type, value = current.fields[final_label]
    if field_type != CEXOLOCSTRING or not isinstance(value, CExoLocString):
        return False

    value.set_text(text, lang_id)
    return True


# ============================================================
# ERF Writer — 모듈 재패킹
# ============================================================

def repack_erf(original_path: Path, output_path: Path, modified_resources: dict):
    """원본 ERF 파일에서 일부 리소스를 교체하여 새 ERF 생성.

    Args:
        original_path: 원본 .mod/.nwm 파일
        output_path: 출력 .mod/.nwm 파일
        modified_resources: {(resref, res_type_id): bytes} 교체할 리소스 데이터
    """
    with open(original_path, 'rb') as f:
        # 원본 헤더 읽기
        header = f.read(160)

    file_type = header[0:4]
    file_version = header[4:8]
    loc_str_count = struct.unpack_from('<I', header, 8)[0]
    loc_str_size = struct.unpack_from('<I', header, 12)[0]
    entry_count = struct.unpack_from('<I', header, 16)[0]
    off_loc_str = struct.unpack_from('<I', header, 20)[0]
    off_key_list = struct.unpack_from('<I', header, 24)[0]

    # 원본 localized strings 읽기
    with open(original_path, 'rb') as f:
        f.seek(off_loc_str)
        loc_str_data = f.read(loc_str_size)

    # 원본 key list + resource data 읽기
    file_type_str, file_version_str, entries = read_erf_entries(original_path)

    # 새 ERF 레이아웃 계산
    new_off_loc_str = 160
    new_off_key_list = new_off_loc_str + loc_str_size
    new_off_res_list = new_off_key_list + entry_count * 24  # 24 bytes per key
    new_off_res_data = new_off_res_list + entry_count * 8   # 8 bytes per resource entry

    # 리소스 데이터 수집 (원본 또는 교체)
    resource_data_list = []
    modified_count = 0

    for resref, res_type, res_id, offset, size in entries:
        key = (resref, res_type)
        if key in modified_resources:
            resource_data_list.append(modified_resources[key])
            modified_count += 1
        else:
            data = read_resource_data(original_path, offset, size)
            resource_data_list.append(data)

    print(f"  Repacking: {entry_count} resources ({modified_count} modified)")

    # ERF 파일 쓰기
    with open(output_path, 'wb') as f:
        # 1. Header (160 bytes)
        new_header = bytearray(header)
        struct.pack_into('<I', new_header, 20, new_off_loc_str)
        struct.pack_into('<I', new_header, 24, new_off_key_list)
        struct.pack_into('<I', new_header, 28, new_off_res_list)
        f.write(bytes(new_header))

        # 2. Localized strings
        f.write(loc_str_data)

        # 3. Key list (24 bytes per entry)
        for resref, res_type, res_id, offset, size in entries:
            resref_bytes = resref.encode('ascii')[:16]
            resref_bytes += b'\x00' * (16 - len(resref_bytes))
            f.write(resref_bytes)
            f.write(struct.pack('<I', res_id))
            f.write(struct.pack('<H', res_type))
            f.write(b'\x00\x00')  # unused

        # 4. Resource list (offsets + sizes)
        current_offset = new_off_res_data
        for data in resource_data_list:
            f.write(struct.pack('<I', current_offset))
            f.write(struct.pack('<I', len(data)))
            current_offset += len(data)

        # 5. Resource data
        for data in resource_data_list:
            f.write(data)

    orig_size = original_path.stat().st_size
    new_size = output_path.stat().st_size
    print(f"  Original: {orig_size:,} bytes → New: {new_size:,} bytes")


# ============================================================
# Build functions
# ============================================================

def build_custom_tlk(config: dict, module_name: str, output_dir: Path) -> Path:
    """커스텀 TLK CSV에서 TLK 파일 빌드"""
    tlk_name = config.get("custom_tlk")
    if not tlk_name:
        return None

    tlk_csv = Path(__file__).parent / module_name / "tlk" / f"{tlk_name}.csv"
    if not tlk_csv.exists():
        print(f"  Custom TLK CSV not found: {tlk_csv}")
        return None

    output_tlk = output_dir / f"{tlk_name}.tlk"

    reference_tlk = TLK_DIR / f"{tlk_name}.tlk"

    print(f"\n  Building custom TLK: {tlk_name}.tlk")

    converter = CSVToTLKConverter(
        tlk_csv,
        encoding='auto',
        reference_tlk=reference_tlk if reference_tlk.exists() else None,
        language_id=0,
    )
    converter.load_csv()
    converter.write_tlk(output_tlk)

    print(f"  → {output_tlk}")
    return output_tlk


def build_gff_resource_index(module_path: Path, entries):
    """ERF 리소스를 스캔하여 GFF 헤더 기반 인덱스 구축.

    NWN 툴셋은 ERF 타입 ID를 GFF 실제 타입과 다르게 저장하는 경우가 있다.
    GFF 파일 헤더를 읽어 실제 타입을 판별한다.

    Returns: {(resref, gff_ext): (erf_type_id, offset, size)}
    """
    index = {}
    for resref, res_type, res_id, offset, size in entries:
        if size < 14:
            continue
        data = read_resource_data(module_path, offset, size)
        try:
            header = data[0:4].decode('ascii', errors='replace').strip('\x00').strip()
            version = data[4:8].decode('ascii', errors='replace').strip('\x00').strip()
        except:
            continue
        if version != 'V3.2':
            continue
        ext = GFF_HEADER_TO_EXT.get(header)
        if ext:
            index[(resref, ext)] = (res_type, offset, size)
    return index


def build_repacked_module(config: dict, module_name: str, output_dir: Path) -> Path:
    """인라인 번역을 적용하여 모듈(.mod/.nwm)을 재패킹.

    Returns: 생성된 모듈 파일 경로, 또는 None
    """
    translations = load_inline_translations(module_name)
    if not translations:
        print(f"\n  No inline translations found")
        return None

    # 번역 대상 리소스 목록 정리
    resources_needed = defaultdict(list)
    for (resref, res_type, field_path, lang_id), text in translations.items():
        resources_needed[(resref, res_type)].append((field_path, lang_id, text))

    print(f"\n  Inline translations: {len(translations)} entries across {len(resources_needed)} resources")

    module_path = get_module_path(config)
    if not module_path or not module_path.exists():
        print(f"  Module file not found: {module_path}")
        return None

    # ERF에서 리소스 인덱스 구축 (GFF 헤더 기반)
    file_type, file_version, entries = read_erf_entries(module_path)
    if file_type is None:
        return None

    resource_index = build_gff_resource_index(module_path, entries)

    # 번역 적용 → modified_resources 구축
    modified_resources = {}  # (resref, erf_type_id) → modified bytes
    applied = 0
    failed = 0

    for (resref, res_ext), trans_list in sorted(resources_needed.items()):
        location = resource_index.get((resref, res_ext))
        if location is None:
            # HAK에 있을 수 있으므로 경고만
            print(f"    Note: {resref}.{res_ext} not in module (may be in HAK)")
            failed += len(trans_list)
            continue

        erf_type_id, offset, size = location
        try:
            data = read_resource_data(module_path, offset, size)
            gff = GffFile.from_bytes(data)
        except Exception as e:
            print(f"    Warning: Failed to parse {resref}.{res_ext}: {e}")
            failed += len(trans_list)
            continue

        resource_applied = 0
        for field_path, lang_id, text in trans_list:
            if set_locstring_in_struct(gff.root, field_path, lang_id, text):
                resource_applied += 1
            else:
                print(f"    Warning: Failed to set {resref}.{res_ext}:{field_path}")
                failed += 1

        if resource_applied > 0:
            modified_resources[(resref, erf_type_id)] = gff.to_bytes()
            applied += resource_applied

    print(f"  Applied: {applied} translations to {len(modified_resources)} resources")
    if failed > 0:
        print(f"  Skipped: {failed} (not in module or failed)")

    if not modified_resources:
        return None

    # 모듈 재패킹
    output_path = output_dir / module_path.name
    repack_erf(module_path, output_path, modified_resources)

    return output_path


def build_module(module_name: str, release: bool = False):
    """단일 모듈 빌드"""
    config = load_module_config(module_name)
    print(f"\n{'='*60}")
    print(f"Building: {config['name']} ({module_name})")
    print(f"{'='*60}")

    if config.get("installed") is False:
        print("  [SKIP] 미설치 모듈")
        return

    module_dir = Path(__file__).parent / module_name
    build_dir = module_dir / "build"
    build_dir.mkdir(parents=True, exist_ok=True)

    # 1. 커스텀 TLK 빌드
    tlk_path = build_custom_tlk(config, module_name, build_dir)

    # 2. 모듈 재패킹 (인라인 텍스트 번역 적용)
    module_path = build_repacked_module(config, module_name, build_dir)

    # 3. release 복사
    if release:
        release_dir = PROJECT_ROOT / "release" / "premium" / module_name
        release_dir.mkdir(parents=True, exist_ok=True)

        if tlk_path and tlk_path.exists():
            dest = release_dir / tlk_path.name
            shutil.copy2(tlk_path, dest)
            print(f"  → release: {dest.relative_to(PROJECT_ROOT)}")

        if module_path and module_path.exists():
            dest = release_dir / module_path.name
            shutil.copy2(module_path, dest)
            print(f"  → release: {dest.relative_to(PROJECT_ROOT)}")

    print(f"\n  Build complete: {module_name}")


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
        description="프리미엄 모듈 번역 빌드"
    )
    parser.add_argument(
        "module", nargs="?",
        help="모듈 디렉토리명 (예: dod, totms, wcoc)"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="전체 모듈 빌드"
    )
    parser.add_argument(
        "--release", action="store_true",
        help="빌드 결과를 release/ 디렉토리에 복사"
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
            build_module(module_name, release=args.release)
    elif args.module:
        build_module(args.module, release=args.release)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
