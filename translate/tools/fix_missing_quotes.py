#!/usr/bin/env python3
"""
영문 대사에 따옴표가 있는데 한글 번역에 없는 경우를 자동 수정하는 스크립트.
지문(StartAction, StartCheck, StartHighlight, [ 등)은 제외합니다.
"""

import csv
import os
import sys
import io

DIALOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'dialog_translated')

# 지문 패턴 (이 패턴을 포함하면 대사가 아닌 지문)
NARRATION_PATTERNS = ['<StartAction>', '<StartCheck>', '<StartHighlight>']

def is_narration(text):
    """지문인지 확인"""
    text = text.strip()
    if text.startswith('['):
        return True
    for pattern in NARRATION_PATTERNS:
        if pattern in text:
            return True
    return False

def text_starts_with_quote(text):
    """실제 텍스트가 따옴표로 시작하는지"""
    return text.strip().startswith('"')

def text_ends_with_quote(text):
    """실제 텍스트가 따옴표로 끝나는지"""
    stripped = text.rstrip()
    return stripped.endswith('"')

def fix_file(filepath, dry_run=False):
    """파일 내 따옴표 누락 수정"""
    fixes = []

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Parse CSV
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)

    if len(rows) < 2:
        return fixes

    header = rows[0]

    # Find column indices
    try:
        eng_idx = header.index('TextEng')
        kor_idx = header.index('Text')
    except ValueError:
        return fixes

    modified = False
    for i, row in enumerate(rows[1:], start=2):  # 1-indexed line number, skip header
        if len(row) <= max(eng_idx, kor_idx):
            continue

        eng_text = row[eng_idx]
        kor_text = row[kor_idx]

        if not eng_text.strip() or not kor_text.strip():
            continue

        # Skip 지문
        if is_narration(eng_text) or is_narration(kor_text):
            continue

        eng_stripped = eng_text.strip()
        kor_stripped = kor_text.strip()

        # Case 1: 영문이 "로 시작하고 "로 끝나는데 한글은 아닌 경우
        eng_starts = eng_stripped.startswith('"')
        eng_ends = eng_stripped.endswith('"')
        kor_starts = kor_stripped.startswith('"')
        kor_ends = kor_stripped.endswith('"')

        if eng_starts and eng_ends and not kor_starts and not kor_ends:
            # 양쪽 따옴표 모두 누락된 케이스만 수정 (가장 안전)
            # start/end만 누락된 경우는 문장 재구성된 것일 수 있어 제외
            strref = row[0] if row[0] else '?'
            new_kor = '"' + kor_text.rstrip() + '"'

            fixes.append({
                'line': i,
                'strref': strref,
                'type': 'both',
                'eng': eng_stripped[:80],
                'old_kor': kor_stripped[:80],
                'new_kor': new_kor.strip()[:80]
            })

            if not dry_run:
                row[kor_idx] = new_kor
                modified = True

    if modified and not dry_run:
        # Write back
        output = io.StringIO()
        writer = csv.writer(output, lineterminator='\n')
        writer.writerows(rows)

        with open(filepath, 'w', encoding='utf-8', newline='') as f:
            f.write(output.getvalue())

    return fixes

def main():
    dry_run = '--dry-run' in sys.argv
    verbose = '--verbose' in sys.argv or '-v' in sys.argv

    if dry_run:
        print("=== DRY RUN MODE (변경 없음) ===\n")

    total_fixes = 0
    file_count = 0

    csv_files = sorted([f for f in os.listdir(DIALOG_DIR) if f.endswith('.csv')])

    for filename in csv_files:
        filepath = os.path.join(DIALOG_DIR, filename)
        fixes = fix_file(filepath, dry_run=dry_run)

        if fixes:
            file_count += 1
            total_fixes += len(fixes)
            print(f"\n📄 {filename} ({len(fixes)}건)")
            if verbose:
                for fix in fixes:
                    print(f"  Line {fix['line']} [StrRef {fix['strref']}] ({fix['type']})")
                    print(f"    EN: {fix['eng']}")
                    print(f"    KR: {fix['old_kor']}")
                    print(f"    → : {fix['new_kor']}")

    print(f"\n{'='*60}")
    print(f"총 {file_count}개 파일, {total_fixes}건 {'발견' if dry_run else '수정'}")

if __name__ == '__main__':
    main()
