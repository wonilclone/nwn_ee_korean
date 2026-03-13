#!/usr/bin/env python3
"""
StrRef 기반 자동 번역 채우기

dialog.tlk 번역 CSV에서 StrRef → 한국어 매핑을 구축하고,
프리미엄 모듈 인라인 CSV의 빈 Text 필드를 자동으로 채운다.

조건:
  - StrRef != -1
  - Text 컬럼이 비어있음
  - dialog.tlk에 해당 StrRef의 한국어 번역이 존재

사용:
  python3 premium/autofill_strref.py              # 전체 모듈 (dry-run)
  python3 premium/autofill_strref.py --apply       # 실제 적용
  python3 premium/autofill_strref.py kingmaker     # 특정 모듈만
  python3 premium/autofill_strref.py --apply --all # 전체 적용
"""
import csv
import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DIALOG_DIR = PROJECT_ROOT / "translate" / "dialog_translated"
PREMIUM_DIR = PROJECT_ROOT / "premium"


def load_strref_map() -> dict:
    """dialog_translated/*.csv에서 StrRef → Text(한국어) 매핑 구축"""
    strref_map = {}  # StrRef → Text(한국어)

    for csv_path in sorted(DIALOG_DIR.glob("*.csv")):
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    strref = int(row["StrRef"])
                except (ValueError, KeyError):
                    continue

                text_kr = row.get("Text", "").strip()

                if strref >= 0 and text_kr:
                    if strref not in strref_map:
                        strref_map[strref] = text_kr

    return strref_map


def process_module(module_dir: Path, strref_map: dict, apply: bool) -> dict:
    """모듈의 인라인 CSV 파일들을 처리"""
    stats = {"filled": 0, "no_kr": 0, "already": 0, "no_strref": 0}

    inline_dir = module_dir / "inline"
    if not inline_dir.exists():
        return stats

    for csv_path in sorted(inline_dir.glob("*.csv")):
        rows = []
        modified = False

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            if not fieldnames or "StrRef" not in fieldnames:
                continue

            for row in reader:
                try:
                    strref = int(row.get("StrRef", -1))
                except ValueError:
                    strref = -1

                text = row.get("Text", "").strip()

                if strref == -1:
                    stats["no_strref"] += 1
                elif text:
                    stats["already"] += 1
                elif strref in strref_map:
                    row["Text"] = strref_map[strref]
                    modified = True
                    stats["filled"] += 1
                else:
                    stats["no_kr"] += 1

                rows.append(row)

        if modified and apply:
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

    return stats


def main():
    args = sys.argv[1:]
    apply = "--apply" in args
    args = [a for a in args if a != "--apply"]

    # 대상 모듈 결정
    if args and args[0] != "--all":
        module_names = args
    else:
        module_names = []
        for d in sorted(PREMIUM_DIR.iterdir()):
            if d.is_dir() and (d / "inline").exists() and (d / "config.py").exists():
                module_names.append(d.name)

    print(f"Loading dialog.tlk translations...")
    strref_map = load_strref_map()
    print(f"  {len(strref_map):,} StrRef → Korean mappings loaded")
    print()

    mode = "APPLY" if apply else "DRY-RUN"
    print(f"Mode: {mode}")
    print("=" * 60)

    total = {"filled": 0, "no_kr": 0, "already": 0, "no_strref": 0}

    for name in module_names:
        module_dir = PREMIUM_DIR / name
        if not module_dir.exists():
            print(f"  [{name}] not found, skipping")
            continue

        stats = process_module(module_dir, strref_map, apply)

        if stats["filled"] > 0:
            print(f"  [{name}] filled: {stats['filled']}, "
                  f"no_kr: {stats['no_kr']}, already: {stats['already']}")

        for k in total:
            total[k] += stats[k]

    print("=" * 60)
    print(f"Total: filled={total['filled']}, "
          f"no_kr={total['no_kr']}, already={total['already']}, no_strref={total['no_strref']}")

    if not apply and total["filled"] > 0:
        print(f"\n  → --apply 플래그를 추가하면 실제로 적용됩니다.")


if __name__ == "__main__":
    main()
