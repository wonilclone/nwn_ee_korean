#!/usr/bin/env python3
"""
NWN:EE 번역 편집기 (Streamlit)

dialog_translated/ 디렉토리의 CSV 파일들을 편집하는 웹 UI입니다.

사용법:
    pip install streamlit
    streamlit run editor.py
"""

import csv
import streamlit as st
from pathlib import Path

TRANSLATE_DIR = Path(__file__).parent
DIALOG_DIR = TRANSLATE_DIR / "dialog_translated"
PAGE_SIZE = 15


def get_ksx1001_hangul():
    """KS X 1001에 정의된 완성형 한글 2,350자를 반환"""
    hangul_chars = set()
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


@st.cache_data
def load_csv_files():
    """CSV 파일 목록 로드"""
    return sorted([f.name for f in DIALOG_DIR.glob("*.csv")])


def load_csv(filename: str) -> list[dict]:
    """CSV 파일 로드"""
    filepath = DIALOG_DIR / filename
    rows = []
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


@st.cache_data
def load_all_csv() -> list[tuple[str, dict]]:
    """모든 CSV 파일 로드 (파일명, 레코드) 튜플 리스트"""
    all_rows = []
    for csv_file in sorted(DIALOG_DIR.glob("*.csv")):
        with open(csv_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                all_rows.append((csv_file.name, row))
    return all_rows


def save_csv(filename: str, rows: list[dict]):
    """CSV 파일 저장"""
    filepath = DIALOG_DIR / filename
    if not rows:
        return

    fieldnames = list(rows[0].keys())
    with open(filepath, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def save_record(filename: str, strref: str, new_text: str):
    """단일 레코드 저장"""
    filepath = DIALOG_DIR / filename
    rows = load_csv(filename)

    for row in rows:
        if row.get('StrRef') == strref:
            row['Text'] = new_text
            break

    save_csv(filename, rows)


def check_ksx1001(text: str, ksx1001_hangul: set) -> list[str]:
    """완성형 범위를 벗어나는 한글 찾기"""
    invalid = []
    for char in text:
        if '\uAC00' <= char <= '\uD7A3' and char not in ksx1001_hangul:
            invalid.append(char)
    return invalid


def find_by_strref(strref: str) -> tuple[str, int, dict] | None:
    """StrRef로 레코드 찾기"""
    for csv_file in DIALOG_DIR.glob("*.csv"):
        rows = load_csv(csv_file.name)
        for idx, row in enumerate(rows):
            if row.get('StrRef') == strref:
                return csv_file.name, idx, row
    return None


def main():
    st.set_page_config(page_title="NWN:EE 번역 편집기", layout="wide")
    st.title("NWN:EE 번역 편집기")

    ksx1001_hangul = get_ksx1001_hangul()

    # 사이드바
    with st.sidebar:
        st.header("모드")

        view_mode = st.radio(
            "보기 모드",
            ["단일 파일", "전체 검색"],
            horizontal=True
        )

        st.divider()
        st.header("검색")

        # StrRef 검색
        strref_input = st.text_input("StrRef 검색", placeholder="예: 12345")
        if strref_input and st.button("검색"):
            result = find_by_strref(strref_input)
            if result:
                filename, idx, row = result
                st.success(f"발견: {filename}")
                st.session_state['selected_file'] = filename
                st.session_state['search_strref'] = strref_input
                st.session_state['view_mode'] = "단일 파일"
            else:
                st.error("찾을 수 없음")

        if view_mode == "단일 파일":
            st.divider()
            # 파일 선택
            csv_files = load_csv_files()
            selected_file = st.selectbox(
                "파일 선택",
                csv_files,
                index=csv_files.index(st.session_state.get('selected_file', csv_files[0])) if st.session_state.get('selected_file') in csv_files else 0
            )
            st.caption(f"총 {len(csv_files)}개 파일")
        else:
            selected_file = None

    # 메인 영역
    if view_mode == "단일 파일" and selected_file:
        # 단일 파일 모드
        rows = load_csv(selected_file)

        # 검색된 StrRef로 스크롤
        search_strref = st.session_state.get('search_strref', '')
        highlight_idx = None
        if search_strref:
            for idx, row in enumerate(rows):
                if row.get('StrRef') == search_strref:
                    highlight_idx = idx
                    break

        st.subheader(f"📄 {selected_file} ({len(rows)}개 레코드)")

        # 필터
        col1, col2 = st.columns([3, 1])
        with col1:
            text_filter = st.text_input("텍스트 필터", placeholder="검색어 입력...", key="single_filter")
        with col2:
            show_invalid_only = st.checkbox("완성형 오류만", key="single_invalid")

        # 필터링
        filtered_rows = []
        for idx, row in enumerate(rows):
            text = row.get('Text', '')

            if text_filter and text_filter.lower() not in text.lower():
                continue

            invalid_chars = check_ksx1001(text, ksx1001_hangul)
            if show_invalid_only and not invalid_chars:
                continue

            filtered_rows.append((idx, row, invalid_chars))

        total_filtered = len(filtered_rows)
        st.caption(f"표시: {total_filtered}개")

        # 페이지네이션
        if total_filtered > PAGE_SIZE:
            total_pages = (total_filtered + PAGE_SIZE - 1) // PAGE_SIZE
            page = st.number_input("페이지", min_value=1, max_value=total_pages, value=1, key="single_page")
            start_idx = (page - 1) * PAGE_SIZE
            end_idx = min(start_idx + PAGE_SIZE, total_filtered)
            st.caption(f"페이지 {page}/{total_pages} (항목 {start_idx + 1}-{end_idx})")
            page_rows = filtered_rows[start_idx:end_idx]
        else:
            page_rows = filtered_rows

        # 편집 폼
        modified = False
        edited_rows = list(rows)

        for idx, row, invalid_chars in page_rows:
            strref = row.get('StrRef', '')
            text = row.get('Text', '')
            text_eng = row.get('TextEng', '')
            speaker_type = row.get('SpeakerType', '')
            speaker_name = row.get('SpeakerName', '')
            dlg = row.get('DLG', '')

            is_highlighted = (idx == highlight_idx)
            container = st.container(border=True)

            with container:
                if is_highlighted:
                    st.markdown("**🔍 검색 결과**")

                # 메타데이터 행
                meta_cols = st.columns([1, 1, 1, 1])
                with meta_cols[0]:
                    st.caption(f"StrRef: {strref}")
                with meta_cols[1]:
                    st.caption(f"Speaker: {speaker_name}")
                with meta_cols[2]:
                    st.caption(f"Type: {speaker_type}")
                with meta_cols[3]:
                    if invalid_chars:
                        st.error(f"⚠️ {', '.join(set(invalid_chars))}")

                # 영어 원문
                if text_eng:
                    st.text_area(
                        "영어 원문",
                        value=text_eng,
                        key=f"eng_{strref}",
                        height=80,
                        disabled=True
                    )

                # 한글 번역
                new_text = st.text_area(
                    "한글 번역",
                    value=text,
                    key=f"single_{strref}",
                    height=80
                )

                if new_text != text:
                    edited_rows[idx] = {**row, 'Text': new_text}
                    modified = True

        if modified:
            st.divider()
            if st.button("💾 저장", type="primary", key="single_save"):
                save_csv(selected_file, edited_rows)
                st.success("저장 완료!")
                st.cache_data.clear()
                st.rerun()

    elif view_mode == "전체 검색":
        # 전체 검색 모드
        st.subheader("🔍 전체 검색")

        col1, col2 = st.columns([3, 1])
        with col1:
            text_filter = st.text_input("텍스트 검색 (필수)", placeholder="검색어 입력...", key="all_filter")
        with col2:
            show_invalid_only = st.checkbox("완성형 오류만", key="all_invalid")

        if not text_filter and not show_invalid_only:
            st.info("검색어를 입력하거나 '완성형 오류만'을 선택하세요.")
            return

        # 로딩
        with st.spinner("전체 파일 검색 중..."):
            all_rows = load_all_csv()

        # 필터링
        filtered = []
        for filename, row in all_rows:
            text = row.get('Text', '')

            if text_filter and text_filter.lower() not in text.lower():
                continue

            invalid_chars = check_ksx1001(text, ksx1001_hangul)
            if show_invalid_only and not invalid_chars:
                continue

            filtered.append((filename, row, invalid_chars))

        total_count = len(filtered)
        st.caption(f"검색 결과: {total_count}개")

        if total_count == 0:
            st.warning("검색 결과가 없습니다.")
            return

        # 페이지네이션
        total_pages = (total_count + PAGE_SIZE - 1) // PAGE_SIZE
        page = st.number_input("페이지", min_value=1, max_value=total_pages, value=1, key="page")

        start_idx = (page - 1) * PAGE_SIZE
        end_idx = min(start_idx + PAGE_SIZE, total_count)

        st.caption(f"페이지 {page}/{total_pages} (항목 {start_idx + 1}-{end_idx})")

        # 현재 페이지 표시
        page_items = filtered[start_idx:end_idx]

        for filename, row, invalid_chars in page_items:
            strref = row.get('StrRef', '')
            text = row.get('Text', '')
            text_eng = row.get('TextEng', '')
            speaker_type = row.get('SpeakerType', '')
            speaker_name = row.get('SpeakerName', '')

            container = st.container(border=True)
            with container:
                # 메타데이터 행
                meta_cols = st.columns([1.5, 1, 1, 1])
                with meta_cols[0]:
                    st.caption(f"📄 {filename}")
                with meta_cols[1]:
                    st.caption(f"StrRef: {strref}")
                with meta_cols[2]:
                    st.caption(f"Speaker: {speaker_name}")
                with meta_cols[3]:
                    if invalid_chars:
                        st.error(f"⚠️ {', '.join(set(invalid_chars))}")

                # 영어 원문
                if text_eng:
                    st.text_area(
                        "영어 원문",
                        value=text_eng,
                        key=f"all_eng_{filename}_{strref}",
                        height=80,
                        disabled=True
                    )

                # 한글 번역
                new_text = st.text_area(
                    "한글 번역",
                    value=text,
                    key=f"all_{filename}_{strref}",
                    height=80
                )

                if new_text != text:
                    if st.button("💾 저장", key=f"save_{filename}_{strref}"):
                        save_record(filename, strref, new_text)
                        st.success(f"저장: {filename} StrRef {strref}")
                        st.cache_data.clear()
                        st.rerun()


if __name__ == '__main__':
    main()
