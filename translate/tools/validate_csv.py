#!/usr/bin/env python3
"""dialog_translated/ CSV 무결성 검사 스크립트

검사 항목:
  [심각] 컬럼 수 불일치 - CSV 깨짐 (따옴표 없는 쉼표 등)
  [심각] StrRef 숫자 아님
  [심각] VolumeVariance/PitchVariance 숫자 아님
  [심각] CSV 파싱 오류
  [경고] 빈 Text(번역) 필드
  [정보] 필드 내 줄바꿈 (멀티라인)

사용법:
  python3 validate_csv.py              # 심각 + 경고 표시
  python3 validate_csv.py --all        # 멀티라인 정보도 표시
  python3 validate_csv.py --critical   # 심각만 표시
"""

import csv
import sys
from pathlib import Path

EXPECTED_COLUMNS = 12
DIALOG_DIR = Path(__file__).parent.parent / "dialog_translated"


def validate_file(filepath: Path) -> tuple[list[str], list[str], int]:
    """Returns (critical_errors, warnings, multiline_count)"""
    criticals = []
    warnings = []
    multiline_count = 0

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception as e:
        return [f"파일 읽기 실패: {e}"], [], 0

    # 멀티라인 검사 (raw)
    in_quote = False
    for line in raw.split("\n"):
        quote_count = line.count('"')
        if in_quote:
            if quote_count % 2 == 1:
                in_quote = False
                multiline_count += 1
        else:
            if quote_count % 2 == 1:
                in_quote = True

    # CSV 파서로 검사
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)

            if header is None:
                return ["빈 파일"], [], 0

            if len(header) != EXPECTED_COLUMNS:
                criticals.append(f"  헤더 컬럼 수: {len(header)} (기대: {EXPECTED_COLUMNS})")

            for row_idx, row in enumerate(reader, 2):
                if len(row) != EXPECTED_COLUMNS:
                    if len(row) == 0:
                        # 빈 줄 (파일 끝 등) - 무시
                        continue
                    text_preview = row[4][:60] if len(row) > 4 else str(row)[:60]
                    criticals.append(
                        f"  줄 {row_idx}: 컬럼 {len(row)}개 (기대 12) | {text_preview}"
                    )
                    continue

                strref = row[0]
                text_kor = row[4]
                vol = row[10]
                pitch = row[11]

                if strref and not strref.isdigit():
                    criticals.append(f"  줄 {row_idx}: StrRef 숫자 아님: '{strref}'")

                if not text_kor.strip():
                    eng_preview = row[3][:50] if row[3] else "(영문없음)"
                    warnings.append(f"  줄 {row_idx}: 빈 번역 | Eng: {eng_preview}")

                for label, val in [("VolumeVariance", vol), ("PitchVariance", pitch)]:
                    if val.strip():
                        try:
                            float(val)
                        except ValueError:
                            criticals.append(f"  줄 {row_idx}: {label} 숫자 아님: '{val}'")

    except csv.Error as e:
        criticals.append(f"  CSV 파싱 오류: {e}")

    return criticals, warnings, multiline_count


def main():
    show_all = "--all" in sys.argv
    critical_only = "--critical" in sys.argv

    if not DIALOG_DIR.exists():
        print(f"디렉토리 없음: {DIALOG_DIR}")
        sys.exit(1)

    csv_files = sorted(DIALOG_DIR.glob("*.csv"))
    print(f"검사 대상: {len(csv_files)}개 파일\n")

    total_critical = 0
    total_warnings = 0
    total_multiline_files = 0
    critical_files = []

    for fp in csv_files:
        crits, warns, ml_count = validate_file(fp)

        has_output = False

        if crits:
            critical_files.append(fp.name)
            total_critical += len(crits)
            print(f"[심각] {fp.name}")
            for e in crits:
                print(e)
            has_output = True

        if warns and not critical_only:
            total_warnings += len(warns)
            if not has_output:
                print(f"[경고] {fp.name}")
            for w in warns:
                print(w)
            has_output = True

        if ml_count > 0:
            total_multiline_files += 1
            if show_all:
                if not has_output:
                    print(f"[정보] {fp.name}")
                print(f"  멀티라인 필드: {ml_count}건")
                has_output = True

        if has_output:
            print()

    # 요약
    print("=" * 60)
    print(f"전체 {len(csv_files)}개 파일 검사 완료\n")

    if total_critical:
        print(f"  [심각] {len(critical_files)}개 파일, {total_critical}건")
        for name in critical_files:
            print(f"         - {name}")
    else:
        print("  [심각] 없음")

    if not critical_only:
        print(f"  [경고] 빈 번역 {total_warnings}건")
    print(f"  [정보] 멀티라인 포함 파일 {total_multiline_files}개")
    print(f"\n옵션: --critical (심각만) | --all (멀티라인 포함)")

    sys.exit(1 if total_critical > 0 else 0)


if __name__ == "__main__":
    main()
