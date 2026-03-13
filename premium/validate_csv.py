#!/usr/bin/env python3
"""프리미엄 모듈 CSV 무결성 검사 스크립트

검사 대상:
  1. inline CSV (Resource,ResType,FieldPath,LangID,StrRef,TextEng,Text)
  2. tlk CSV (StrRef,Text,SoundRef,VolumeVariance,PitchVariance)

검사 항목:
  [심각] 컬럼 수 불일치 - CSV 깨짐 (따옴표 없는 쉼표 등)
  [심각] StrRef 형식 오류 (inline: 숫자 또는 -1, tlk: 숫자)
  [심각] LangID 숫자 아님 (inline)
  [심각] VolumeVariance/PitchVariance 숫자 아님 (tlk)
  [심각] CSV 파싱 오류
  [경고] 영문 있는데 번역 비어있음
  [경고] StrRef 중복 (tlk)

사용법:
  python3 validate_csv.py                # 전체 모듈 검사
  python3 validate_csv.py eremor chess   # 특정 모듈만 검사
  python3 validate_csv.py --critical     # 심각만 표시
"""

import csv
import sys
from pathlib import Path

INLINE_COLUMNS = 7   # Resource,ResType,FieldPath,LangID,StrRef,TextEng,Text
TLK_COLUMNS = 5      # StrRef,Text,SoundRef,VolumeVariance,PitchVariance
PREMIUM_DIR = Path(__file__).parent

# 미번역 경고 제외 대상
SKIP_WARN_RES_TYPES = {"uts", "utt"}   # 사운드 오브젝트, 트리거 (게임에 표시 안됨)
SKIP_WARN_FILE_TYPES = {"git.csv"}     # 인스턴스 오버라이드 (utc/uti 등에서 번역)


def validate_inline(filepath: Path) -> tuple[list[str], list[str]]:
    """inline CSV 검사. Returns (criticals, warnings)."""
    criticals = []
    warnings = []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)

            if header is None:
                return ["빈 파일"], []

            if len(header) != INLINE_COLUMNS:
                criticals.append(f"  헤더 컬럼 수: {len(header)} (기대: {INLINE_COLUMNS})")

            for row_idx, row in enumerate(reader, 2):
                if len(row) == 0:
                    continue
                if len(row) != INLINE_COLUMNS:
                    preview = ",".join(row[:4])[:80]
                    criticals.append(
                        f"  줄 {row_idx}: 컬럼 {len(row)}개 (기대 {INLINE_COLUMNS}) | {preview}"
                    )
                    continue

                resource, res_type, field_path, lang_id, strref, text_eng, text_kor = row

                # LangID 검사
                if lang_id.strip() and not lang_id.strip().isdigit():
                    criticals.append(f"  줄 {row_idx}: LangID 숫자 아님: '{lang_id}'")

                # StrRef 검사 (-1 허용)
                strref_s = strref.strip()
                if strref_s:
                    try:
                        int(strref_s)
                    except ValueError:
                        criticals.append(f"  줄 {row_idx}: StrRef 형식 오류: '{strref_s}'")

                # 번역 누락 경고 (영문 있는데 한글 없음)
                if text_eng.strip() and not text_kor.strip():
                    # resref와 영문이 동일하면 내부 이름이므로 건너뜀
                    if text_eng.strip() == resource.strip():
                        continue
                    eng_preview = text_eng[:60]
                    warnings.append(f"  줄 {row_idx}: 미번역 | {eng_preview}")

    except csv.Error as e:
        criticals.append(f"  CSV 파싱 오류: {e}")

    return criticals, warnings


def validate_tlk(filepath: Path) -> tuple[list[str], list[str]]:
    """tlk CSV 검사. Returns (criticals, warnings)."""
    criticals = []
    warnings = []
    seen_strrefs = {}

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)

            if header is None:
                return ["빈 파일"], []

            if len(header) != TLK_COLUMNS:
                criticals.append(f"  헤더 컬럼 수: {len(header)} (기대: {TLK_COLUMNS})")

            for row_idx, row in enumerate(reader, 2):
                if len(row) == 0:
                    continue
                if len(row) != TLK_COLUMNS:
                    preview = ",".join(row)[:80]
                    criticals.append(
                        f"  줄 {row_idx}: 컬럼 {len(row)}개 (기대 {TLK_COLUMNS}) | {preview}"
                    )
                    continue

                strref, text, sound_ref, vol, pitch = row

                # StrRef 검사
                strref_s = strref.strip()
                if strref_s and not strref_s.isdigit():
                    criticals.append(f"  줄 {row_idx}: StrRef 숫자 아님: '{strref_s}'")
                elif strref_s:
                    if strref_s in seen_strrefs:
                        warnings.append(
                            f"  줄 {row_idx}: StrRef {strref_s} 중복 (첫 출현: 줄 {seen_strrefs[strref_s]})"
                        )
                    seen_strrefs[strref_s] = row_idx

                # VolumeVariance/PitchVariance 검사
                for label, val in [("VolumeVariance", vol), ("PitchVariance", pitch)]:
                    if val.strip():
                        try:
                            float(val)
                        except ValueError:
                            criticals.append(f"  줄 {row_idx}: {label} 숫자 아님: '{val}'")

    except csv.Error as e:
        criticals.append(f"  CSV 파싱 오류: {e}")

    return criticals, warnings


def validate_module(module_dir: Path, critical_only: bool) -> tuple[int, int]:
    """하나의 모듈 디렉토리를 검사한다. Returns (critical_count, warning_count)."""
    total_crits = 0
    total_warns = 0
    module_name = module_dir.name

    # inline CSV 검사
    inline_dir = module_dir / "inline"
    if inline_dir.is_dir():
        for csv_file in sorted(inline_dir.glob("*.csv")):
            # uts.csv, git.csv 는 미번역 경고 제외
            file_type = csv_file.stem  # e.g. "uts", "git"
            skip_warns = csv_file.name in SKIP_WARN_FILE_TYPES or file_type in SKIP_WARN_RES_TYPES
            crits, warns = validate_inline(csv_file)
            if skip_warns:
                warns = []
            rel_path = f"{module_name}/inline/{csv_file.name}"

            if crits:
                total_crits += len(crits)
                print(f"[심각] {rel_path}")
                for e in crits:
                    print(e)
                print()

            if warns and not critical_only:
                total_warns += len(warns)
                print(f"[경고] {rel_path} - 미번역 {len(warns)}건")
                print()

    # tlk CSV 검사
    tlk_dir = module_dir / "tlk"
    if tlk_dir.is_dir():
        for csv_file in sorted(tlk_dir.glob("*.csv")):
            crits, warns = validate_tlk(csv_file)
            rel_path = f"{module_name}/tlk/{csv_file.name}"

            if crits:
                total_crits += len(crits)
                print(f"[심각] {rel_path}")
                for e in crits:
                    print(e)
                print()

            if warns:
                total_warns += len(warns)
                if not critical_only:
                    print(f"[경고] {rel_path}")
                    for w in warns:
                        print(w)
                    print()

    return total_crits, total_warns


def main():
    critical_only = "--critical" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    # 대상 모듈 결정
    if args:
        modules = [PREMIUM_DIR / name for name in args]
        for m in modules:
            if not m.is_dir():
                print(f"Error: 모듈 디렉토리 없음: {m.name}")
                sys.exit(1)
    else:
        modules = sorted(
            d for d in PREMIUM_DIR.iterdir()
            if d.is_dir() and (d / "inline").is_dir()
        )

    print(f"검사 대상: {len(modules)}개 모듈\n")

    grand_crits = 0
    grand_warns = 0
    critical_modules = []

    for module_dir in modules:
        crits, warns = validate_module(module_dir, critical_only)
        grand_crits += crits
        grand_warns += warns
        if crits:
            critical_modules.append(module_dir.name)

    # 요약
    print("=" * 60)
    print(f"전체 {len(modules)}개 모듈 검사 완료\n")

    if grand_crits:
        print(f"  [심각] {len(critical_modules)}개 모듈, {grand_crits}건")
        for name in critical_modules:
            print(f"         - {name}")
    else:
        print("  [심각] 없음")

    if not critical_only:
        print(f"  [경고] 미번역 등 {grand_warns}건")

    print(f"\n옵션: --critical (심각만)")

    sys.exit(1 if grand_crits > 0 else 0)


if __name__ == "__main__":
    main()
