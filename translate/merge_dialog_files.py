#!/usr/bin/env python3
"""
분할된 대화 파일들을 다시 하나로 합치는 스크립트
CSV 병합 후 TLK 파일도 함께 생성
"""

import csv
import re
import sys
from pathlib import Path
from collections import OrderedDict

# csv_to_tlk 모듈 import (상위 디렉토리에 있음)
sys.path.insert(0, str(Path(__file__).parent.parent))
from csv_to_tlk import CSVToTLKConverter


def validate_records(all_records):
    """병합된 레코드의 데이터 품질 검증"""
    print("\n=== 데이터 품질 검증 ===")

    issues = []
    korean_pattern = re.compile(r'[\uac00-\ud7af]')

    for strref, record in all_records.items():
        text = record.get('Text', '')
        text_eng = record.get('TextEng', '')

        # 1. Text가 비어있지만 TextEng가 있는 경우
        if not text and text_eng and text_eng.strip():
            # 숫자만 있는 코드는 제외 (예: 100767, 453_452)
            text_eng_stripped = text_eng.strip()
            if not text_eng_stripped.isdigit() and not re.match(r'^\d+_\d+$', text_eng_stripped):
                issues.append({
                    'strref': strref,
                    'type': 'empty_text',
                    'message': f"Text 비어있음, TextEng: {text_eng[:50]}..."
                })

        # 2. TextEng에 한글이 포함된 경우 (데이터 손상)
        #    단, Text에 번역이 있으면 실제 문제는 아닐 수 있음 (경고만)
        if text_eng and korean_pattern.search(text_eng):
            # Text가 비어있거나 TextEng와 같으면 심각한 문제
            if not text or text == text_eng:
                issues.append({
                    'strref': strref,
                    'type': 'korean_in_texteng',
                    'message': f"TextEng에 한글 포함: {text_eng[:50]}..."
                })
            else:
                # Text에 번역이 있으면 경고만 (데이터는 사용 가능)
                issues.append({
                    'strref': strref,
                    'type': 'korean_in_texteng_warning',
                    'message': f"TextEng에 한글 혼재 (번역은 있음): {text_eng[:50]}..."
                })

        # 3. Text와 TextEng가 완전히 동일한 경우 (미번역)
        if text and text_eng and text == text_eng:
            # 태그만 있는 경우는 제외
            if not (text.startswith('<') and text.endswith('>')):
                issues.append({
                    'strref': strref,
                    'type': 'untranslated',
                    'message': f"미번역: {text[:50]}..."
                })

    # 결과 출력
    empty_text = [i for i in issues if i['type'] == 'empty_text']
    korean_in_eng = [i for i in issues if i['type'] == 'korean_in_texteng']
    korean_in_eng_warn = [i for i in issues if i['type'] == 'korean_in_texteng_warning']
    untranslated = [i for i in issues if i['type'] == 'untranslated']

    if empty_text:
        print(f"\n[오류] Text가 비어있는 항목: {len(empty_text)}개")
        for issue in empty_text[:10]:
            print(f"  StrRef {issue['strref']}: {issue['message']}")
        if len(empty_text) > 10:
            print(f"  ... 외 {len(empty_text) - 10}개")

    if korean_in_eng:
        print(f"\n[오류] TextEng에 한글이 있는 항목 (번역 없음): {len(korean_in_eng)}개")
        for issue in korean_in_eng:
            print(f"  StrRef {issue['strref']}: {issue['message']}")

    if korean_in_eng_warn:
        print(f"\n[경고] TextEng에 한글 혼재 (번역은 있음): {len(korean_in_eng_warn)}개")

    if untranslated:
        print(f"\n[정보] 미번역 항목 (Text == TextEng): {len(untranslated)}개")

    critical_issues = len(empty_text) + len(korean_in_eng)
    if critical_issues == 0:
        print("\n✓ 심각한 데이터 문제 없음")
    else:
        print(f"\n⚠ 심각한 문제 {critical_issues}개 발견 - 수정 필요")

    return issues


def merge_dialog_files():
    """분할된 대화 파일들을 병합"""

    # 입력 디렉토리들
    dialog_translated_dir = Path("dialog_translated")
    # common_dir = Path("common")

    # 출력 파일
    output_file = Path("dialog.csv")

    # 모든 레코드를 StrRef 기준으로 정렬하기 위한 딕셔너리
    all_records = {}
    all_fieldnames = set()

    print("=== 분할된 파일들 병합 시작 ===")

    # 1. dialog_translated 디렉토리의 모든 CSV 파일 처리
    if dialog_translated_dir.exists():
        print(f"\ndialog_translated 디렉토리 처리 중...")
        dialog_files = list(dialog_translated_dir.glob("*.csv"))
        print(f"발견된 파일: {len(dialog_files)}개")

        for csv_file in dialog_files:
            try:
                with open(csv_file, 'r', encoding='utf-8-sig') as f:
                    reader = csv.DictReader(f)

                    # 모든 필드명 수집 (BOM 문자 제거)
                    if reader.fieldnames:
                        # BOM 문자를 제거하고 필드명 정규화
                        normalized_fieldnames = [field.lstrip('\ufeff') for field in reader.fieldnames]
                        all_fieldnames.update(normalized_fieldnames)

                    record_count = 0
                    for row in reader:
                        strref = row.get('StrRef', '')
                        if strref:
                            # BOM이 포함된 키를 정규화
                            normalized_row = {k.lstrip('\ufeff'): v for k, v in row.items()}
                            all_records[strref] = normalized_row
                            record_count += 1

                    print(f"  {csv_file.name}: {record_count}개 레코드")

            except Exception as e:
                print(f"  오류 - {csv_file.name}: {e}")

    # 3. 데이터 품질 검증
    validate_records(all_records)

    # 4. StrRef 기준으로 정렬하여 출력
    print(f"\n병합된 총 레코드: {len(all_records)}개")

    if all_records and all_fieldnames:
        # 빈 문자열 필드명 제거
        all_fieldnames.discard('')
        all_fieldnames.discard(None)

        # 필드명 정렬 (StrRef가 먼저 오도록)
        fieldnames = ['StrRef'] + sorted([f for f in all_fieldnames if f != 'StrRef'])

        # StrRef를 숫자로 정렬
        sorted_strrefs = sorted(all_records.keys(), key=lambda x: int(x) if x.isdigit() else float('inf'))

        with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()

            for strref in sorted_strrefs:
                # 모든 필드에 대해 기본값 설정
                row_data = {field: all_records[strref].get(field, '') for field in fieldnames}
                writer.writerow(row_data)

        print(f"\n병합 완료: {output_file}")
        print(f"총 {len(all_records)}개 레코드가 StrRef 순으로 정렬되어 저장됨")
        print(f"총 필드 수: {len(fieldnames)}개")

        return output_file
    else:
        print("병합할 데이터가 없습니다.")
        return None


def create_tlk_from_csv(csv_path: Path, tlk_path: Path, debug_mode: bool = False):
    """CSV 파일에서 TLK 파일 생성 (csv_to_tlk 모듈 사용)

    Args:
        csv_path: 입력 CSV 파일 경로
        tlk_path: 출력 TLK 파일 경로
        debug_mode: True면 텍스트 앞에 [StrRef] 추가 (검수용)
    """
    print(f"\n=== TLK 파일 생성 시작 ===")

    # 원본 TLK 경로 (NWN:EE 기본 경로)
    reference_tlk = Path("/Users/mac/Library/Application Support/Steam/steamapps/common/Neverwinter Nights/lang/en/data/dialog.tlk")

    converter = CSVToTLKConverter(
        csv_path,
        encoding='auto',
        reference_tlk=reference_tlk if reference_tlk.exists() else None,
        language_id=0,  # 원본과 동일하게
        debug_mode=debug_mode
    )
    converter.load_csv()
    converter.write_tlk(tlk_path)

    if debug_mode:
        print(f"\n⚠️  검수 모드로 빌드됨: 모든 텍스트 앞에 [StrRef]가 추가됨")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='분할된 대화 파일들을 병합하고 TLK 생성')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='검수 모드: 텍스트 앞에 [StrRef] 추가 (예: [21]안녕하세요)')
    args = parser.parse_args()

    csv_file = merge_dialog_files()

    if csv_file:
        # TLK 파일 경로 설정
        tlk_file = csv_file.with_suffix('.tlk')
        create_tlk_from_csv(csv_file, tlk_file, debug_mode=args.debug)