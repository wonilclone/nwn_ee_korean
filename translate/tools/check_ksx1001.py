#!/usr/bin/env python3
"""
완성형 한글(KS X 1001) 검사 스크립트

dialog_translated/ 디렉토리의 CSV 파일들에서 완성형 한글 2,350자를 벗어나는 문자를 찾습니다.
완성형 폰트만 베이킹된 환경에서 표시되지 않는 글자를 사전에 검출합니다.

사용법:
    python3 check_ksx1001.py                    # dialog_translated/ 전체 검사
    python3 check_ksx1001.py <csv_file>         # 특정 파일 검사
"""

import csv
import sys
from pathlib import Path


def get_ksx1001_hangul():
    """KS X 1001에 정의된 완성형 한글 2,350자를 반환"""
    hangul_chars = set()

    # KS X 1001 한글 영역: EUC-KR 바이트 범위 0xB0A1-0xC8FE
    for first in range(0xB0, 0xC9):
        for second in range(0xA1, 0xFF):
            if first == 0xC8 and second > 0xFE:
                continue
            try:
                byte_seq = bytes([first, second])
                char = byte_seq.decode('euc-kr')
                if '\uAC00' <= char <= '\uD7A3':
                    hangul_chars.add(char)
            except:
                pass

    return hangul_chars


def check_csv_file(csv_path: Path, ksx1001_hangul: set) -> dict:
    """CSV 파일에서 완성형을 벗어나는 한글을 검사"""
    non_ksx1001_chars = {}

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):
            text = row.get('Text', '')
            strref = row.get('StrRef', '')

            for i, char in enumerate(text):
                if '\uAC00' <= char <= '\uD7A3':  # 한글 음절
                    if char not in ksx1001_hangul:
                        if char not in non_ksx1001_chars:
                            non_ksx1001_chars[char] = []
                        context = text[max(0, i-10):i+11]
                        non_ksx1001_chars[char].append({
                            'file': csv_path.name,
                            'row': row_num,
                            'strref': strref,
                            'context': context
                        })

    return non_ksx1001_chars


def check_directory(dir_path: Path) -> bool:
    """디렉토리 내 모든 CSV 파일 검사"""
    ksx1001_hangul = get_ksx1001_hangul()
    print(f"KS X 1001 완성형 한글: {len(ksx1001_hangul)}자")
    print(f"검사 디렉토리: {dir_path}")
    print("-" * 60)

    csv_files = sorted(dir_path.glob("*.csv"))
    if not csv_files:
        print("CSV 파일이 없습니다.")
        return True

    all_non_ksx1001 = {}
    files_checked = 0

    for csv_file in csv_files:
        result = check_csv_file(csv_file, ksx1001_hangul)
        files_checked += 1

        for char, occurrences in result.items():
            if char not in all_non_ksx1001:
                all_non_ksx1001[char] = []
            all_non_ksx1001[char].extend(occurrences)

    print(f"검사한 파일: {files_checked}개")

    # 결과 출력
    if all_non_ksx1001:
        total_occurrences = sum(len(v) for v in all_non_ksx1001.values())
        print(f"\n⚠️  완성형을 벗어나는 한글 발견!")
        print(f"   - 문자 종류: {len(all_non_ksx1001)}개")
        print(f"   - 총 발생 횟수: {total_occurrences}회\n")

        for char, occurrences in sorted(all_non_ksx1001.items(), key=lambda x: -len(x[1])):
            print(f"'{char}' (U+{ord(char):04X}) - {len(occurrences)}회")
            for occ in occurrences[:5]:
                print(f"  [{occ['file']}] 행 {occ['row']}, StrRef {occ['strref']}: ...{occ['context']}...")
            if len(occurrences) > 5:
                print(f"  ... 외 {len(occurrences)-5}건")
            print()

        return False
    else:
        print("\n✅ 모든 한글이 완성형(KS X 1001) 범위 내에 있습니다.")
        return True


def main():
    script_dir = Path(__file__).parent
    translate_dir = script_dir.parent
    default_dir = translate_dir / "dialog_translated"

    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
        if target.is_file():
            ksx1001_hangul = get_ksx1001_hangul()
            print(f"KS X 1001 완성형 한글: {len(ksx1001_hangul)}자")
            print(f"검사 파일: {target}")
            print("-" * 60)
            result = check_csv_file(target, ksx1001_hangul)
            if result:
                total = sum(len(v) for v in result.values())
                print(f"\n⚠️  완성형을 벗어나는 한글: {len(result)}종, {total}회")
                sys.exit(1)
            else:
                print("\n✅ 모든 한글이 완성형 범위 내에 있습니다.")
                sys.exit(0)
        elif target.is_dir():
            success = check_directory(target)
            sys.exit(0 if success else 1)
        else:
            print(f"오류: 경로를 찾을 수 없습니다: {target}")
            sys.exit(1)
    else:
        if not default_dir.exists():
            print(f"오류: 디렉토리를 찾을 수 없습니다: {default_dir}")
            sys.exit(1)
        success = check_directory(default_dir)
        sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
