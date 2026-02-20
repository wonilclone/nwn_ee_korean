#!/usr/bin/env python3
"""
particle_deep_scan.py - 조사-받침 불일치 스캔 + 패턴 중복제거

위반 패턴에서 '단어+조사' 패턴을 추출하고 빈도순으로 정렬하여
오탐 필터 대상과 실제 수정 대상을 쉽게 구분할 수 있게 합니다.
"""

import csv
import os
import re
import sys
from collections import defaultdict, Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TRANSLATED_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "dialog_translated")

HANGUL_START = 0xAC00
HANGUL_END = 0xD7A3

def is_hangul(ch):
    return HANGUL_START <= ord(ch) <= HANGUL_END

def has_batchim(ch):
    return (ord(ch) - HANGUL_START) % 28 != 0

def jongseong_index(ch):
    return (ord(ch) - HANGUL_START) % 28

# 조사 뒤에 올 수 있는 경계 문자
BOUNDARY = set(' ,.\t\n\r!?:;)]}"\'/…—~。、')

def is_boundary(text, idx):
    if idx >= len(text):
        return True
    return text[idx] in BOUNDARY

def extract_word_before(text, particle_idx):
    """조사 앞의 한글 단어를 추출 (공백 기준)"""
    end = particle_idx
    start = end
    while start > 0 and is_hangul(text[start - 1]):
        start -= 1
    if start == end:
        return None
    return text[start:end]

def scan_text(text):
    """텍스트에서 4가지 조사 불일치를 찾아 (category, word+particle, context) 반환"""
    results = []

    for i, ch in enumerate(text):
        if i == 0:
            continue
        prev = text[i - 1]
        if not is_hangul(prev):
            continue
        if not is_boundary(text, i + 1):
            continue

        word = extract_word_before(text, i)
        if not word:
            continue

        category = None

        if ch == '을' and not has_batchim(prev):
            category = '을→를'
        elif ch == '를' and has_batchim(prev):
            category = '를→을'
        elif ch == '과' and not has_batchim(prev):
            category = '과→와'
        elif ch == '와' and has_batchim(prev):
            category = '와→과'
        elif ch == '가' and has_batchim(prev):
            category = '가→이'
        elif ch == '이' and not has_batchim(prev):
            category = '이→가'
        elif ch == '은' and not has_batchim(prev):
            category = '은→는'
        elif ch == '는' and has_batchim(prev):
            category = '는→은'

        if category:
            pattern = word + ch  # e.g. "마을", "효과"
            ctx_start = max(0, i - 15)
            ctx_end = min(len(text), i + 10)
            context = text[ctx_start:ctx_end]
            results.append((category, pattern, context))

    return results


def main():
    csv_files = sorted(f for f in os.listdir(TRANSLATED_DIR) if f.lower().endswith('.csv'))
    print(f"Scanning {len(csv_files)} CSV files...")

    # category -> {pattern: (count, [(file, strref, context)])}
    cat_patterns = defaultdict(lambda: defaultdict(lambda: [0, []]))

    for fname in csv_files:
        filepath = os.path.join(TRANSLATED_DIR, fname)
        for enc in ('utf-8-sig', 'utf-8', 'cp949'):
            try:
                with open(filepath, 'r', encoding=enc) as f:
                    reader = csv.reader(f)
                    next(reader, None)  # skip header
                    for row in reader:
                        if len(row) < 5:
                            continue
                        strref = row[0]
                        text = row[4]
                        if not text or not text.strip():
                            continue
                        for category, pattern, context in scan_text(text):
                            entry = cat_patterns[category][pattern]
                            entry[0] += 1
                            if len(entry[1]) < 3:  # 예시 최대 3개만
                                entry[1].append((fname, strref, context))
                break
            except UnicodeDecodeError:
                continue
            except Exception as e:
                print(f"  WARNING: {fname}: {e}", file=sys.stderr)
                break

    # 카테고리별로 패턴 빈도순 출력
    categories = ['을→를', '를→을', '과→와', '와→과', '가→이', '이→가', '은→는', '는→은']

    for cat in categories:
        patterns = cat_patterns.get(cat, {})
        if not patterns:
            continue

        total = sum(v[0] for v in patterns.values())
        sorted_patterns = sorted(patterns.items(), key=lambda x: -x[1][0])

        print(f"\n{'='*80}")
        print(f"  [{cat}] 총 {total}건, 고유 패턴 {len(sorted_patterns)}개")
        print(f"{'='*80}")

        for pattern, (count, examples) in sorted_patterns:
            print(f"\n  \"{pattern}\" × {count}회")
            for fname, strref, ctx in examples:
                ctx_clean = ctx.replace('\n', '\\n').replace('\r', '')
                print(f"    ├ {fname}:{strref} \"{ctx_clean}\"")

    # 요약
    print(f"\n{'='*80}")
    print("  SUMMARY")
    print(f"{'='*80}")
    total_all = 0
    for cat in categories:
        patterns = cat_patterns.get(cat, {})
        total = sum(v[0] for v in patterns.values())
        unique = len(patterns)
        if total > 0:
            print(f"  {cat}: {total}건 ({unique} 고유 패턴)")
            total_all += total
    print(f"  총합: {total_all}건")


if __name__ == '__main__':
    main()
