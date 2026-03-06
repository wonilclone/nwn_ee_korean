#!/usr/bin/env python3
"""
Find dialogue lines where English text has quotes but Korean text doesn't.
Skips 지문 (narrative/stage directions).
"""

import csv
import glob
import os
import sys

DIALOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dialog_translated")

def is_stage_direction(text):
    """Check if text is a stage direction (지문), not dialogue."""
    stripped = text.strip()
    if not stripped:
        return False
    # StartAction, StartCheck, StartHighlight tags
    if '<StartAction>' in stripped or '<StartCheck>' in stripped or '<StartHighlight>' in stripped:
        return True
    # Starts with [ bracket (stage direction)
    if stripped.startswith('['):
        return True
    return False

def strip_outer_quotes(text):
    """Check if text starts and/or ends with a quote character."""
    stripped = text.strip()
    starts = stripped.startswith('"')
    ends = stripped.endswith('"')
    return starts, ends

def main():
    csv_files = sorted(glob.glob(os.path.join(DIALOG_DIR, "*.csv")))
    print(f"Scanning {len(csv_files)} CSV files in {DIALOG_DIR}\n")

    total_found = 0
    results_by_file = {}

    for filepath in csv_files:
        filename = os.path.basename(filepath)
        file_results = []

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if not header:
                    continue

                for line_num, row in enumerate(reader, start=2):  # line 1 is header
                    if len(row) < 5:
                        continue

                    strref = row[0]
                    text_eng = row[3]
                    text_kor = row[4]

                    # Skip empty fields
                    if not text_eng.strip() or not text_kor.strip():
                        continue

                    # Skip stage directions
                    if is_stage_direction(text_eng):
                        continue

                    eng_starts, eng_ends = strip_outer_quotes(text_eng)
                    kor_starts, kor_ends = strip_outer_quotes(text_kor)

                    # We only care if English has quotes that Korean doesn't
                    if not eng_starts and not eng_ends:
                        continue

                    missing = []
                    if eng_starts and not kor_starts:
                        missing.append("start")
                    if eng_ends and not kor_ends:
                        missing.append("end")

                    if not missing:
                        continue

                    file_results.append({
                        'line': line_num,
                        'strref': strref,
                        'missing': '+'.join(missing),
                        'eng': text_eng[:60],
                        'kor': text_kor[:60],
                    })

        except Exception as e:
            print(f"Error reading {filename}: {e}", file=sys.stderr)
            continue

        if file_results:
            results_by_file[filename] = file_results
            total_found += len(file_results)

    # Print results grouped by file
    for filename, results in sorted(results_by_file.items()):
        print(f"=== {filename} ({len(results)} issues) ===")
        for r in results:
            eng_display = r['eng'].replace('\n', '\\n')
            kor_display = r['kor'].replace('\n', '\\n')
            print(f"  Line {r['line']:>5} | StrRef {r['strref']:>7} | Missing: {r['missing']:<10} | ENG: {eng_display}")
            print(f"         {'':>7}   {'':>7}   {'':10} | KOR: {kor_display}")
        print()

    print(f"\n{'='*60}")
    print(f"Total: {total_found} issues in {len(results_by_file)} files")

if __name__ == '__main__':
    main()
