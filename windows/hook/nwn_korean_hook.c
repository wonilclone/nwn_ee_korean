/**
 * NWN:EE Windows x64 한글 패치 DLL
 *
 * Phase 2: AurGetTTFTexture 후킹으로 한글 글리프 베이크 (2,606개)
 * Phase 4: Nuklear UI 한글 지원 (미완성 - 비활성화)
 *
 * 빌드 (Visual Studio):
 *   cl /LD /O2 nwn_korean_hook.c /Fe:nwn_korean_hook.dll
 *
 * 빌드 (MinGW):
 *   gcc -shared -O2 -o nwn_korean_hook.dll nwn_korean_hook.c
 */

#include <windows.h>
#include <psapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <malloc.h>

#include "cp949_utils.h"

#pragma comment(lib, "psapi.lib")

// ============================================================================
// 상수 정의
// ============================================================================

// Phase 2: 함수 포인터 후킹
// Export 심볼 분석 결과:
// 0x0140b278: ?AurGetTTFTexture@@3P6A... (함수 포인터 변수 - 여기를 후킹!)
// 0x000f6d70: ?GetTTFTexture@CAuroraInterface@@... (실제 함수)
#define AUR_GET_TTF_TEXTURE_PTR_RVA  0x0140b278

// Phase 3: GetSymbolCoords 인라인 후킹
// GetSymbolCoords(fontInfo, glyph_index, out1, out2) - UV 좌표 및 advance 반환
// 디스어셈블리 분석: 0x1400ebb10 (RVA = 0xebb10)
#define GET_SYMBOL_COORDS_RVA  0x000ebb10

// Phase 4 - Stage 1: nk_command_buffer_push 진단 훅
// Nuklear 커맨드 버퍼 할당 함수 - TEXT 명령 로깅
#define NK_CMD_BUF_PUSH_RVA  0xC10434

// Phase 4 - Stage 2: nk_draw_text 텍스트 변환 훅
// NK_COMMAND_TEXT를 생성하는 함수 - 텍스트 파라미터 진단/변환
#define NK_DRAW_TEXT_RVA  0x952A10

// 한글 글리프 설정
#define GLYPH_BASE_INDEX  256
#define TOTAL_GLYPH_COUNT  2606  // 256 (ASCII) + 25*94 (한글)

// 로그 설정
// 로그 파일은 실행 파일과 같은 디렉토리에 생성됨
#define LOG_FILE  "nwn_korean.log"
#define MAX_LOG_COUNT  200

// ============================================================================
// 타입 정의
// ============================================================================

/**
 * AurGetTTFTexture 함수 시그니처
 *
 * 실제 시그니처: void GetTTFTexture(const char*, float, int*, int, float, float, float, void*)
 *
 * CRITICAL: float 파라미터 때문에 정확한 타입으로 선언해야 함!
 */
typedef void (*AurGetTTFTexture_fn)(
    const char* ttf_path,
    float pixel_height,
    int* chars_array,
    int count,
    float p5,
    float p6,
    float p7,
    void* out_data
);

/**
 * GetSymbolCoords 함수 시그니처
 *
 * Windows x64 thiscall:
 *   rcx = this (CAurFontInfo*)
 *   edx = glyph_index
 *   r8 = out1 (UV 좌표 구조체 포인터)
 *   r9 = out2 (advance 등 메트릭 포인터)
 *
 * out1 구조체 (추정): { float u1, v1, u2, v2 } - 텍스처 UV 좌표
 * out2 구조체 (추정): { float advance_x, advance_y, ... } - 글리프 메트릭
 */
typedef void (*GetSymbolCoords_fn)(
    void* fontInfo,     // rcx: this
    int glyph_index,    // edx
    void* out1,         // r8
    void* out2          // r9
);

// ============================================================================
// 전역 변수
// ============================================================================

static HMODULE nwmain_base = NULL;
static AurGetTTFTexture_fn original_bake = NULL;
static uint32_t* korean_chars = NULL;
static volatile int bake_hook_active = 0;
static int log_count = 0;
static CRITICAL_SECTION log_cs;

// Phase 3: GetSymbolCoords 후킹
static GetSymbolCoords_fn original_get_symbol_coords = NULL;
static uint8_t get_symbol_coords_original_bytes[14];  // 원본 명령어 백업
static volatile int get_symbol_coords_hook_active = 0;
static int get_symbol_coords_log_count = 0;
#define MAX_GET_SYMBOL_COORDS_LOG 20

// ============================================================================
// Phase 4: Nuklear 한글 지원 (Latin-1 손상된 CP949 → UTF-8 변환)
// ============================================================================

// nk_user_font 구조체 (Nuklear 내부)
// offset +0x00: userdata (handle)
// offset +0x08: height (float)
// offset +0x10: width 함수 포인터
// offset +0x18: query 함수 포인터

// nk_draw_text 함수 시그니처
// Windows x64 (MSVC):
//   rcx = nk_command_buffer*
//   rdx = nk_rect* (16바이트 구조체 -> 포인터로 전달)
//   r8  = const char* text
//   r9d = int len
//   [rsp+28h] = const nk_user_font* font
//   [rsp+30h] = nk_color bg (4바이트)
//   [rsp+38h] = nk_color fg (4바이트)
//
// nk_draw_text가 nk_draw_list_add_text의 상위 레벨 함수이고
// 파라미터 레이아웃이 더 단순함

// UTF-8 변환 버퍼
static char nk_utf8_buffer[8192];
static CRITICAL_SECTION nk_buffer_cs;

// 통계
static volatile LONG nk_total_calls = 0;
static volatile LONG nk_conversion_count = 0;

// 베이크된 폰트 높이 추적 (nk_user_font 스캔용)
static volatile float baked_heights[8] = {0};
static volatile int baked_height_count = 0;

// Phase 4 - New: nk_user_font->width 콜백 훅
typedef float (*nk_text_width_fn_t)(void* userdata, float height, const char* text, int len);
static nk_text_width_fn_t original_nk_width_fn = NULL;
static volatile int nk_width_hook_active = 0;
static volatile LONG nk_width_total_calls = 0;
static volatile LONG nk_width_korean_found = 0;
static int nk_width_log_count = 0;
#define MAX_NK_WIDTH_LOG 100

// 전방 선언
static void write_log(const char* format, ...);

// ============================================================================
// Phase 4: Latin-1 손상된 CP949 → UTF-8 변환 함수
// ============================================================================

/**
 * Latin-1으로 손상된 CP949 문자열 감지
 *
 * TLK 로더가 CP949 바이트를 Latin-1으로 해석하면:
 * - CP949 '제' = 0xC1 0xA6
 * - Latin-1 해석: Á (U+00C1), ¦ (U+00A6)
 * - UTF-8 인코딩: C3 81 C2 A6
 *
 * 따라서 UTF-8 2바이트 시퀀스 (C2/C3 XX) 형태로 나타남
 */
static int is_latin1_corrupted_utf8(const char* text, int len) {
    if (!text || len < 2) return 0;

    // UTF-8 2바이트 시퀀스가 연속으로 나타나는지 확인
    // Latin-1 0x80~0xFF → UTF-8 C2 80 ~ C3 BF
    unsigned char b0 = (unsigned char)text[0];
    unsigned char b1 = (unsigned char)text[1];

    // C2 또는 C3로 시작하는 UTF-8 시퀀스
    if ((b0 == 0xC2 || b0 == 0xC3) && (b1 >= 0x80 && b1 <= 0xBF)) {
        return 1;  // Latin-1 손상된 CP949로 추정
    }

    return 0;
}

/**
 * Latin-1 손상된 UTF-8 → CP949 원본 복원 → NK 글리프 인덱스 변환
 *
 * 입력: UTF-8 인코딩된 Latin-1 문자열 (원본은 CP949)
 * 출력: NK chardata 인덱스를 UTF-8 코드포인트로 인코딩한 문자열
 *
 * 엔진의 NK 폰트 lookup은 chardata[codepoint] 직접 인덱싱.
 * Unicode 코드포인트(U+AC00+)를 사용하면 배열 범위 초과.
 * 대신 chardata 인덱스(256-2605)를 코드포인트로 사용.
 *
 * 과정:
 * 1. UTF-8 디코딩하여 Latin-1 바이트 복원 (C2/C3 XX → 0x80-0xFF)
 * 2. 연속된 두 바이트를 CP949로 해석
 * 3. KSX1001 순차 인덱스 계산: (high - 0xB0) * 94 + (low - 0xA1)
 * 4. chardata 인덱스 = 256 + KSX1001 인덱스
 * 5. chardata 인덱스를 UTF-8 코드포인트로 인코딩
 */
static int convert_latin1_corrupted_to_nk_glyphs(const char* src, int src_len, char* dst, int dst_size) {
    if (!src || !dst || src_len <= 0 || dst_size <= 0) return 0;

    int si = 0;  // source index
    int di = 0;  // dest index

    // 먼저 UTF-8 → 바이트 배열로 디코딩
    unsigned char bytes[4096];
    int byte_count = 0;

    while (si < src_len && byte_count < 4096) {
        unsigned char b = (unsigned char)src[si];

        if (b < 0x80) {
            // ASCII
            bytes[byte_count++] = b;
            si++;
        }
        else if ((b & 0xE0) == 0xC0 && si + 1 < src_len) {
            // UTF-8 2바이트 시퀀스 (C2-DF XX)
            unsigned char b1 = (unsigned char)src[si + 1];
            if ((b1 & 0xC0) == 0x80) {
                uint16_t cp = ((b & 0x1F) << 6) | (b1 & 0x3F);
                // Latin-1 범위 (U+0080~U+00FF)는 원래 바이트로 복원
                if (cp <= 0xFF) {
                    bytes[byte_count++] = (unsigned char)cp;
                } else {
                    bytes[byte_count++] = b;
                    bytes[byte_count++] = b1;
                }
                si += 2;
            } else {
                bytes[byte_count++] = b;
                si++;
            }
        }
        else {
            // 그 외 (3바이트 UTF-8 등): 바이트 단위로 복사
            bytes[byte_count++] = b;
            si++;
        }
    }

    // bytes 배열을 CP949로 해석하여 NK 글리프 인덱스로 변환
    int bi = 0;
    while (bi < byte_count && di < dst_size - 3) {
        unsigned char b0 = bytes[bi];

        if (b0 < 0x80) {
            // ASCII: chardata[0-127] 직접 대응
            dst[di++] = b0;
            bi++;
        }
        else if (b0 >= 0xB0 && b0 <= 0xC8 && bi + 1 < byte_count) {
            unsigned char b1 = bytes[bi + 1];

            if (b1 >= 0xA1 && b1 <= 0xFE) {
                // CP949 → KSX1001 순차 인덱스 → chardata 인덱스
                int glyph_idx = 256 + (b0 - 0xB0) * 94 + (b1 - 0xA1);

                // 글리프 인덱스를 UTF-8 코드포인트로 인코딩
                // 256-2047: 2바이트 UTF-8 (C4 80 ~ DF BF)
                // 2048-2605: 3바이트 UTF-8 (E0 A0 80 ~ E0 A8 AD)
                if (glyph_idx < 0x800) {
                    dst[di++] = (char)(0xC0 | (glyph_idx >> 6));
                    dst[di++] = (char)(0x80 | (glyph_idx & 0x3F));
                } else {
                    dst[di++] = (char)(0xE0 | (glyph_idx >> 12));
                    dst[di++] = (char)(0x80 | ((glyph_idx >> 6) & 0x3F));
                    dst[di++] = (char)(0x80 | (glyph_idx & 0x3F));
                }
                bi += 2;
                continue;
            }
            // 변환 실패: 원본 바이트 유지
            dst[di++] = b0;
            bi++;
        }
        else {
            dst[di++] = b0;
            bi++;
        }
    }

    dst[di] = '\0';
    return di;
}

/**
 * CP949 문자열을 NK 글리프 인덱스로 직접 변환
 */
static int convert_cp949_to_nk_glyphs(const char* src, int src_len, char* dst, int dst_size) {
    if (!src || !dst || src_len <= 0 || dst_size <= 0) return 0;

    int si = 0;
    int di = 0;

    while (si < src_len && di < dst_size - 3) {
        unsigned char b0 = (unsigned char)src[si];

        if (b0 < 0x80) {
            dst[di++] = src[si++];
        }
        else if (b0 >= 0xB0 && b0 <= 0xC8 && si + 1 < src_len) {
            unsigned char b1 = (unsigned char)src[si + 1];

            if (b1 >= 0xA1 && b1 <= 0xFE) {
                int glyph_idx = 256 + (b0 - 0xB0) * 94 + (b1 - 0xA1);

                if (glyph_idx < 0x800) {
                    dst[di++] = (char)(0xC0 | (glyph_idx >> 6));
                    dst[di++] = (char)(0x80 | (glyph_idx & 0x3F));
                } else {
                    dst[di++] = (char)(0xE0 | (glyph_idx >> 12));
                    dst[di++] = (char)(0x80 | ((glyph_idx >> 6) & 0x3F));
                    dst[di++] = (char)(0x80 | (glyph_idx & 0x3F));
                }
                si += 2;
                continue;
            }
            dst[di++] = src[si++];
        }
        else {
            dst[di++] = src[si++];
        }
    }

    dst[di] = '\0';
    return di;
}

/**
 * 텍스트 변환 처리
 *
 * @param text  입력 텍스트
 * @param len   텍스트 길이
 * @param out_buf 변환된 텍스트 출력 버퍼
 * @param out_size 출력 버퍼 크기
 * @return 변환된 길이 (0이면 변환 안 함)
 */
static int nk_process_text(const char* text, int len, char* out_buf, int out_size) {
    if (!text || len <= 0) return 0;

    // 비ASCII 바이트 찾기
    int has_non_ascii = 0;
    for (int i = 0; i < len; i++) {
        if ((unsigned char)text[i] >= 0x80) {
            has_non_ascii = 1;
            break;
        }
    }

    // 비ASCII가 없으면 변환 불필요
    if (!has_non_ascii) return 0;

    // Latin-1 손상된 UTF-8 감지 (C2/C3 XX 패턴)
    for (int i = 0; i < len - 1; i++) {
        unsigned char b0 = (unsigned char)text[i];
        unsigned char b1 = (unsigned char)text[i + 1];
        if ((b0 == 0xC2 || b0 == 0xC3) && (b1 >= 0x80 && b1 <= 0xBF)) {
            return convert_latin1_corrupted_to_nk_glyphs(text, len, out_buf, out_size);
        }
    }

    // 이미 변환된 UTF-8인지 확인 (in-place 변환 후 재호출 방지)
    // 글리프 인덱스 UTF-8 (C4-DF/E0)은 유효한 UTF-8 시퀀스를 형성
    // CP949는 유효한 UTF-8이 아님 (bare 0xB0-0xC8 바이트)
    int valid_utf8 = 1;
    for (int i = 0; i < len; ) {
        unsigned char b = (unsigned char)text[i];
        if (b < 0x80) {
            i++;
        } else if ((b & 0xE0) == 0xC0 && i + 1 < len &&
                   ((unsigned char)text[i + 1] & 0xC0) == 0x80) {
            i += 2;
        } else if ((b & 0xF0) == 0xE0 && i + 2 < len &&
                   ((unsigned char)text[i + 1] & 0xC0) == 0x80 &&
                   ((unsigned char)text[i + 2] & 0xC0) == 0x80) {
            i += 3;
        } else {
            valid_utf8 = 0;
            break;
        }
    }
    if (valid_utf8) return 0;  // 이미 변환됨 또는 유효한 UTF-8

    // 원본 CP949 감지 (유효한 UTF-8이 아닌 경우만)
    for (int i = 0; i < len - 1; i++) {
        unsigned char b0 = (unsigned char)text[i];
        if (b0 >= 0xB0 && b0 <= 0xC8) {
            unsigned char b1 = (unsigned char)text[i + 1];
            if (b1 >= 0xA1 && b1 <= 0xFE) {
                return convert_cp949_to_nk_glyphs(text, len, out_buf, out_size);
            }
        }
    }

    return 0;
}

// ============================================================================
// 로그 함수
// ============================================================================

static void write_log(const char* format, ...) {
    if (log_count >= MAX_LOG_COUNT) return;

    EnterCriticalSection(&log_cs);

    FILE* log = fopen(LOG_FILE, "a");
    if (log) {
        va_list args;
        va_start(args, format);
        vfprintf(log, format, args);
        va_end(args);
        fclose(log);
        log_count++;
    }

    LeaveCriticalSection(&log_cs);
}

// ============================================================================
// Phase 4: 이전 nk_draw_list_add_text 래퍼 코드 (제거됨)
// → Stage 2 코드로 대체 (아래 nk_draw_text 진단 훅 참조)
// ============================================================================




// ============================================================================
// nwmain 베이스 주소 찾기
// ============================================================================

static HMODULE find_nwmain_base(void) {
    // 현재 프로세스의 모든 모듈 순회
    HMODULE modules[1024];
    DWORD needed;

    if (!EnumProcessModules(GetCurrentProcess(), modules, sizeof(modules), &needed)) {
        return NULL;
    }

    int count = needed / sizeof(HMODULE);
    for (int i = 0; i < count; i++) {
        char name[MAX_PATH];
        if (GetModuleFileNameA(modules[i], name, sizeof(name))) {
            // nwmain.exe 찾기
            if (strstr(name, "nwmain.exe")) {
                return modules[i];
            }
        }
    }

    return NULL;
}

// ============================================================================
// 한글 문자 배열 초기화
// ============================================================================

static void init_korean_chars(uint32_t* original_chars) {
    if (korean_chars) return;

    korean_chars = (uint32_t*)malloc(TOTAL_GLYPH_COUNT * sizeof(uint32_t));
    if (!korean_chars) {
        write_log("[Bake] ERROR: Failed to allocate korean_chars\n");
        return;
    }

    // 원본 256자 복사
    memcpy(korean_chars, original_chars, 256 * sizeof(uint32_t));

    // KS X 1001 완성형 한글 2350자 추가
    // 글리프 인덱스 = 256 + (lead - 0xB0) * 94 + (trail - 0xA1)
    int glyph_idx = 256;
    for (int lead = 0xB0; lead <= 0xC8; lead++) {
        for (int trail = 0xA1; trail <= 0xFE; trail++) {
            uint32_t unicode = cp949_to_unicode((uint8_t)lead, (uint8_t)trail);
            if (unicode != 0) {
                korean_chars[glyph_idx] = unicode;
            } else {
                // 유효하지 않은 코드는 공백으로
                korean_chars[glyph_idx] = 0x0020;
            }
            glyph_idx++;
        }
    }

    write_log("[Bake] Initialized %d characters (256 base + %d Korean)\n",
              TOTAL_GLYPH_COUNT, glyph_idx - 256);
    write_log("[Bake] Sample: glyph[256]=U+%04X (가), glyph[1512]=U+%04X (시)\n",
              korean_chars[256],
              korean_chars[256 + (0xBD - 0xB0) * 94 + (0xC3 - 0xA1)]);
}

// ============================================================================
// AurGetTTFTexture 후킹 함수
// ============================================================================

// 정확한 시그니처로 선언
void my_AurGetTTFTexture(
    const char* ttf_path,
    float pixel_height,
    int* chars_array,
    int count,
    float p5,
    float p6,
    float p7,
    void* out_data
)
{
    if (!original_bake) {
        write_log("[Bake] ERROR: original_bake is NULL\n");
        return;
    }

    write_log("[Bake] ttf=%s height=%.1f chars=%p count=%d\n",
              ttf_path ? ttf_path : "NULL", pixel_height, chars_array, count);
    write_log("[Bake] p5=%.1f p6=%.1f p7=%.6f out_data=%p\n", p5, p6, p7, out_data);

    // 베이크된 폰트 높이 저장 (nk_user_font 스캔에 사용)
    if (baked_height_count < 8) {
        baked_heights[baked_height_count] = pixel_height;
        baked_height_count++;
        write_log("[Bake] Stored height[%d]=%.1f for NK font scan\n",
                  baked_height_count - 1, pixel_height);
    }

    // 256자 베이크 요청 감지 및 확장
    if (count == 256 && chars_array != NULL) {
        write_log("[Bake] MATCH! Expanding 256 -> %d chars\n", TOTAL_GLYPH_COUNT);

        init_korean_chars((uint32_t*)chars_array);

        if (korean_chars) {
            write_log("[Bake] Verify: chars[0]=U+%04X chars[255]=U+%04X chars[256]=U+%04X chars[2605]=U+%04X\n",
                      korean_chars[0], korean_chars[255], korean_chars[256], korean_chars[2605]);

            // 2606자로 직접 베이크 (원본 bake 함수가 내부에서 배열 할당 처리)
            write_log("[Bake] Baking with %d chars (Korean expanded)...\n", TOTAL_GLYPH_COUNT);
            original_bake(ttf_path, pixel_height, korean_chars, TOTAL_GLYPH_COUNT, p5, p6, p7, out_data);
            write_log("[Bake] Done\n");
            return;
        }
    }

    // Pass-through
    write_log("[Bake] Pass-through (count=%d)\n", count);
    original_bake(ttf_path, pixel_height, chars_array, count, p5, p6, p7, out_data);
}

// ============================================================================
// Phase 3: GetSymbolCoords 후킹 (한글 글리프 advance 조정)
// ============================================================================

/**
 * GetSymbolCoords 후킹 함수
 *
 * 한글 글리프(인덱스 >= 256)의 경우 advance width를 조정하여
 * 문자 침범 문제 해결
 */
void my_GetSymbolCoords(void* fontInfo, int glyph_index, void* out1, void* out2) {
    // 원본 함수 호출
    original_get_symbol_coords(fontInfo, glyph_index, out1, out2);

    // 디버깅 로그 (처음 몇 번만)
    if (get_symbol_coords_log_count < MAX_GET_SYMBOL_COORDS_LOG) {
        float* out1_floats = (float*)out1;
        float* out2_floats = (float*)out2;

        write_log("[GetSymCoords #%d] idx=%d out1=[%.2f,%.2f,%.2f,%.2f] out2=[%.2f,%.2f]\n",
                  get_symbol_coords_log_count, glyph_index,
                  out1_floats[0], out1_floats[1], out1_floats[2], out1_floats[3],
                  out2_floats[0], out2_floats[1]);
        get_symbol_coords_log_count++;
    }

    // 한글 글리프(인덱스 >= 256)의 경우 advance 조정
    if (glyph_index >= GLYPH_BASE_INDEX && out2 != NULL) {
        float* out2_floats = (float*)out2;

        // out2[0]이 advance_x라고 가정
        // 한글은 전각 문자이므로 advance를 약 1.8~2.0배로 조정
        float original_advance = out2_floats[0];
        float adjusted_advance = original_advance * 1.8f;

        // 최소값 보장 (너무 작으면 문자가 겹침)
        if (adjusted_advance < 10.0f) {
            adjusted_advance = 10.0f;
        }

        out2_floats[0] = adjusted_advance;

        // 디버깅 로그
        if (get_symbol_coords_log_count < MAX_GET_SYMBOL_COORDS_LOG + 10) {
            write_log("[GetSymCoords] Korean glyph %d: advance %.2f -> %.2f\n",
                      glyph_index, original_advance, adjusted_advance);
        }
    }
}

/**
 * GetSymbolCoords 인라인 후킹 설치
 *
 * 함수 시작 부분을 jmp 명령어로 교체하여 우리 함수로 리다이렉트
 */
static BOOL install_get_symbol_coords_hook(void) {
    void* func_addr = (void*)((uintptr_t)nwmain_base + GET_SYMBOL_COORDS_RVA);

    write_log("[Hook] GetSymbolCoords at: %p (RVA 0x%08x)\n", func_addr, GET_SYMBOL_COORDS_RVA);

    // 원본 바이트 백업 (14 bytes - jmp [rip+0] + 8byte addr)
    memcpy(get_symbol_coords_original_bytes, func_addr, 14);

    // 트램폴린 생성을 위해 원본 함수 호출 가능하도록
    // 간단한 방법: VirtualAlloc으로 실행 가능 메모리 할당하고 원본 코드 + jmp 작성
    void* trampoline = VirtualAlloc(NULL, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!trampoline) {
        write_log("[Hook] ERROR: VirtualAlloc failed for trampoline\n");
        return FALSE;
    }

    // 트램폴린: 원본 14바이트 + jmp to (func_addr + 14)
    uint8_t* tramp = (uint8_t*)trampoline;
    memcpy(tramp, get_symbol_coords_original_bytes, 14);

    // jmp [rip+0] 형식 (FF 25 00 00 00 00 + 8바이트 주소)
    tramp[14] = 0xFF;
    tramp[15] = 0x25;
    tramp[16] = 0x00;
    tramp[17] = 0x00;
    tramp[18] = 0x00;
    tramp[19] = 0x00;
    *(uint64_t*)(tramp + 20) = (uint64_t)func_addr + 14;

    original_get_symbol_coords = (GetSymbolCoords_fn)trampoline;

    write_log("[Hook] Trampoline at: %p\n", trampoline);

    // 원본 함수 시작 부분을 jmp my_GetSymbolCoords로 교체
    DWORD old_protect;
    if (!VirtualProtect(func_addr, 14, PAGE_EXECUTE_READWRITE, &old_protect)) {
        write_log("[Hook] ERROR: VirtualProtect failed (error %d)\n", GetLastError());
        VirtualFree(trampoline, 0, MEM_RELEASE);
        return FALSE;
    }

    // jmp [rip+0] 형식
    uint8_t* hook = (uint8_t*)func_addr;
    hook[0] = 0xFF;
    hook[1] = 0x25;
    hook[2] = 0x00;
    hook[3] = 0x00;
    hook[4] = 0x00;
    hook[5] = 0x00;
    *(uint64_t*)(hook + 6) = (uint64_t)my_GetSymbolCoords;

    VirtualProtect(func_addr, 14, old_protect, &old_protect);

    get_symbol_coords_hook_active = 1;
    write_log("[Hook] GetSymbolCoords hook installed!\n");
    write_log("[Hook] Original: %p -> Hook: %p -> Trampoline: %p\n",
              func_addr, my_GetSymbolCoords, trampoline);

    return TRUE;
}

// ============================================================================
// Phase 2: Bake 함수 후킹 설치
// ============================================================================

static BOOL install_bake_hook(void) {
    if (!nwmain_base) {
        write_log("[Hook] ERROR: nwmain_base is NULL\n");
        return FALSE;
    }

    write_log("[Hook] nwmain base: %p\n", nwmain_base);

    // 함수 포인터 후킹 (간단하고 안전)
    void** func_ptr = (void**)((uintptr_t)nwmain_base + AUR_GET_TTF_TEXTURE_PTR_RVA);
    write_log("[Hook] Function pointer at: %p (RVA 0x%08x)\n", func_ptr, AUR_GET_TTF_TEXTURE_PTR_RVA);
    write_log("[Hook] Current value: %p\n", *func_ptr);

    // 함수 포인터가 아직 초기화되지 않았는지 확인
    if (*func_ptr == NULL || (uintptr_t)(*func_ptr) < 0x140000000) {
        write_log("[Hook] WARNING: Function pointer not initialized yet, will retry later\n");
        return FALSE;
    }

    // 원본 함수 포인터 저장
    original_bake = (AurGetTTFTexture_fn)(*func_ptr);

    // 함수 포인터를 우리 함수로 교체
    DWORD old_protect;
    if (!VirtualProtect(func_ptr, sizeof(void*), PAGE_READWRITE, &old_protect)) {
        write_log("[Hook] ERROR: VirtualProtect failed (error %d)\n", GetLastError());
        return FALSE;
    }

    *func_ptr = (void*)my_AurGetTTFTexture;
    VirtualProtect(func_ptr, sizeof(void*), old_protect, &old_protect);

    bake_hook_active = 1;
    write_log("[Hook] Successfully hooked AurGetTTFTexture function pointer\n");
    write_log("[Hook] Original: %p, Hook: %p\n", original_bake, my_AurGetTTFTexture);

    return TRUE;
}

// ============================================================================
// 지연 훅킹 스레드
// ============================================================================

static DWORD WINAPI bake_hook_thread(LPVOID param) {
    (void)param;

    write_log("[Bake Thread] Started polling for function pointer initialization...\n");

    // 최대 30초 대기 (100ms 간격)
    for (int attempts = 0; attempts < 300; attempts++) {
        if (bake_hook_active) {
            write_log("[Bake Thread] Hook already active, exiting\n");
            return 0;
        }

        // 함수 포인터가 초기화되었는지 확인
        void** func_ptr = (void**)((uintptr_t)nwmain_base + AUR_GET_TTF_TEXTURE_PTR_RVA);

        if (*func_ptr && (uintptr_t)(*func_ptr) >= 0x140000000) {
            // 유효한 함수 포인터 발견!
            if (install_bake_hook()) {
                write_log("[Bake Thread] SUCCESS! Hook installed after %d attempts\n", attempts);
                return 0;
            }
        }

        Sleep(100);

        if (attempts % 50 == 0 && attempts > 0) {
            write_log("[Bake Thread] Still waiting... attempt %d\n", attempts);
        }
    }

    write_log("[Bake Thread] TIMEOUT - function pointer not initialized\n");
    return 0;
}




// ============================================================================
// Phase 4 - Stage 1: nk_command_buffer_push 할당 훅
// ============================================================================
//
// "Allocate & Edit" 전략의 첫 단계.
// Nuklear 커맨드 버퍼에 TEXT 명령이 push될 때 할당 크기를 확장하여
// 나중에 Latin-1 → UTF-8 변환을 위한 여유 공간을 확보한다.
//
// nk_command_buffer_push 시그니처 (Nuklear 소스):
//   void* nk_command_buffer_push(nk_command_buffer*, enum nk_command_type, nk_size)
//
// Windows x64 (MSVC):
//   rcx = nk_command_buffer*
//   edx = type (0x10 = NK_COMMAND_TEXT)
//   r8  = size (할당 크기)
//   r9  = (alignment 등)
//
// 프롤로그 (15바이트, RVA 0xC10434):
//   +00: 48 8B C4              mov rax, rsp           (3)
//   +03: 4C 89 48 20           mov [rax+20h], r9      (4)
//   +07: 4C 89 40 18           mov [rax+18h], r8      (4)
//   +0B: 48 89 50 10           mov [rax+10h], rdx     (4)
//
// 핵심: mov rax, rsp 패턴이지만, naked wrapper가 RSP를 복원한 채
// trampoline으로 jmp하면 rax가 올바른 값을 캡처함.

static void* nk_push_trampoline = NULL;
static void* original_nk_cmd_buf_push = NULL;
static volatile int nk_push_hook_active = 0;
static volatile LONG nk_push_text_count = 0;
static volatile LONG nk_pending_processed = 0;  // 진단: pending 처리 횟수
static int nk_push_log_count = 0;
#define MAX_NK_PUSH_LOG 30
#define NK_PUSH_HOOK_SIZE 15

// Return-address hijacking으로 TEXT 커맨드 포인터 캡처
// TEXT push만 hijack → post-hook에서 rax(커맨드 포인터) 캡처
//
// CRITICAL: 포인터 변수는 `void* volatile`로 선언해야 포인터 자체가 volatile.
// `volatile void*`는 "volatile void를 가리키는 포인터"로 포인터 변수 자체는 non-volatile.
// post-hook 어셈블리에서 쓰기 때문에 GCC -O2가 C 분석으로 항상 NULL로 최적화함.
static void* volatile pending_text_cmd = NULL;
static volatile uint64_t pending_text_size = 0;
static volatile int pending_was_text = 0;
static volatile uint64_t saved_push_return_addr = 0;
static void* nk_push_post_hook_addr = NULL;  // install 시 설정
static volatile LONG nk_post_hook_fire_count = 0;  // 진단: post-hook 실행 횟수

// 진단: 트램폴린이 쓰는 rax 값 캡처 (주소 불일치 검증용)
static volatile uint64_t post_hook_diag_rax = 0xDEADDEADDEADDEADULL;

// 비휘발 레지스터 캡처 (naked wrapper에서 저장, handler에서 읽기)
// 호출자(인라인된 nk_draw_text)의 text 포인터가 비휘발 레지스터에 보존됨
// [0]=rbx [1]=rsi [2]=rdi [3]=rbp [4]=r12 [5]=r13 [6]=r14 [7]=r15
static volatile uint64_t saved_nonvol_regs[8] = {0};

// 진단 카운터
static volatile LONG prev_text_cmds_found = 0;
static volatile LONG prev_korean_cmds_found = 0;

// 프롤로그 검증 패턴
static const uint8_t NK_PUSH_EXPECTED_PROLOGUE[15] = {
    0x48, 0x8B, 0xC4,                   // mov rax, rsp
    0x4C, 0x89, 0x48, 0x20,             // mov [rax+20h], r9
    0x4C, 0x89, 0x40, 0x18,             // mov [rax+18h], r8
    0x48, 0x89, 0x50, 0x10              // mov [rax+10h], rdx
};

// pending TEXT 커맨드 진단 덤프
// push N+1 진입 시 호출 → push N의 커맨드 데이터가 이미 채워져 있음
static void process_pending_text(void* cmd_ptr, uint64_t size) {
    if (!cmd_ptr) return;

    static int dump_count = 0;
    if (dump_count >= 20) return;
    dump_count++;

    uint8_t* p = (uint8_t*)cmd_ptr;
    int dump_bytes = (size < 128) ? (int)size : 128;

    // 안전 검사
    if (IsBadReadPtr(p, dump_bytes)) {
        write_log("[NK TextCmd #%d] BAD pointer %p\n", dump_count, cmd_ptr);
        return;
    }

    write_log("[NK TextCmd #%d] ptr=%p alloc_size=%llu\n",
              dump_count, cmd_ptr, (unsigned long long)size);

    // hex + ASCII 덤프
    for (int row = 0; row < dump_bytes; row += 16) {
        char line[120];
        int lp = 0;
        char ascii[20];
        int ap = 0;

        lp += sprintf(line + lp, "  +%02x: ", row);
        for (int col = 0; col < 16 && (row + col) < dump_bytes; col++) {
            uint8_t b = p[row + col];
            lp += sprintf(line + lp, "%02x ", b);
            ascii[ap++] = (b >= 0x20 && b < 0x7F) ? (char)b : '.';
        }
        ascii[ap] = '\0';
        write_log("%s |%s|\n", line, ascii);
    }

    // 8바이트 경계마다 포인터 추적: 문자열 찾기
    for (int off = 0; off + 8 <= dump_bytes; off += 8) {
        uint64_t val = *(uint64_t*)(p + off);
        if (val > 0x10000 && val < 0x7FFFFFFFFFFF &&
            !IsBadReadPtr((void*)val, 8)) {
            unsigned char* sp = (unsigned char*)val;
            // 문자열 가능성 확인: ASCII 또는 C2/C3 패턴
            if ((sp[0] >= 0x20 && sp[0] < 0x7F) || sp[0] == 0xC2 || sp[0] == 0xC3) {
                int slen = 0;
                while (slen < 80 && !IsBadReadPtr(sp + slen, 1) && sp[slen] != 0)
                    slen++;
                if (slen >= 2) {
                    char hex[200];
                    int hp = 0;
                    int show = slen < 40 ? slen : 40;
                    for (int j = 0; j < show && hp < 190; j++)
                        hp += sprintf(hex + hp, "%02x ", sp[j]);
                    write_log("  +%02x ptr -> string(%d): %s\n", off, slen, hex);
                }
            }
        }
    }
}

// C 핸들러 - naked 래퍼에서 call로 호출됨
// 비휘발 레지스터 + 호출자 스택에서 텍스트 포인터 탐색
// 개선: CP949 하이바이트 감지, 코드 포인터 노이즈 필터, 로그 한도 분리
uint64_t nk_push_handler(uint32_t type, uint64_t size, uint64_t* ret_addr_ptr, void* buf);

// 문자열 품질 검사: 텍스트인지 코드/바이너리인지 판별
// 반환: 0=텍스트 아님, 1=ASCII만, 2=하이바이트 포함
static int classify_string(const unsigned char* sp, int slen,
                           int* out_highbyte, int* out_c2c3, int* out_cp949) {
    int printable = 0, highbyte = 0, control = 0;
    for (int j = 0; j < slen; j++) {
        if (sp[j] >= 0x20 && sp[j] <= 0x7E) printable++;
        else if (sp[j] >= 0x80) highbyte++;
        else control++;
    }
    // 텍스트성(printable + highbyte)이 70% 미만이면 코드/바이너리
    int textlike = printable + highbyte;
    if (textlike * 10 < slen * 7) return 0;

    *out_highbyte = highbyte;

    // C2/C3 패턴 (Latin-1 corrupted → UTF-8)
    *out_c2c3 = 0;
    for (int j = 0; j < slen - 1; j++) {
        if ((sp[j] == 0xC2 || sp[j] == 0xC3) && sp[j+1] >= 0x80) {
            *out_c2c3 = 1;
            break;
        }
    }

    // CP949 패턴 (raw Korean: first byte 0x81-0xFE, second byte 0x41-0xFE)
    // 좁은 범위: B0-C8 + A1-FE (완성형 한글 가/까~힣)
    *out_cp949 = 0;
    for (int j = 0; j < slen - 1; j++) {
        if (sp[j] >= 0x81 && sp[j] <= 0xFE &&
            sp[j+1] >= 0x41 && sp[j+1] <= 0xFE) {
            *out_cp949 = 1;
            break;
        }
    }

    return (highbyte > 0) ? 2 : 1;
}

// 문자열 hex + ascii 덤프 헬퍼
static void dump_string(const unsigned char* sp, int slen, int max_hex) {
    char hex[400];
    int hp = 0;
    int show = slen < max_hex ? slen : max_hex;
    for (int j = 0; j < show && hp < 390; j++)
        hp += sprintf(hex + hp, "%02x ", sp[j]);
    write_log("  hex: %s\n", hex);

    if (slen <= 200) {
        char txt[300];
        int tp = 0;
        for (int j = 0; j < slen && tp < 290; j++)
            txt[tp++] = (sp[j] >= 0x20 && sp[j] < 0x7F) ? (char)sp[j] : '.';
        txt[tp] = 0;
        write_log("  ascii: %s\n", txt);
    }
}

uint64_t nk_push_handler(uint32_t type, uint64_t size, uint64_t* ret_addr_ptr, void* buf) {
    if (type == 0x10) {
        InterlockedIncrement(&nk_push_text_count);
    }

    // type=0x10만 처리
    if (type != 0x10) return size;

    // 한글 50개 수집하면 진단 완료
    if (prev_korean_cmds_found > 50) return size;

    static const char* reg_names[] = {"rbx","rsi","rdi","rbp","r12","r13","r14","r15"};

    // --- 비휘발 레지스터 스캔 ---
    for (int ri = 0; ri < 8; ri++) {
        uint64_t val = saved_nonvol_regs[ri];
        if (val < 0x10000 || val > 0x7FFFFFFFFFFF) continue;
        if (IsBadReadPtr((void*)val, 4)) continue;

        unsigned char* sp = (unsigned char*)val;

        // NULL-terminated 문자열 길이 측정 (하이바이트도 허용)
        int slen = 0;
        while (slen < 300 && !IsBadReadPtr(sp + slen, 1) && sp[slen] != 0)
            slen++;
        if (slen < 4) continue;

        int highbyte = 0, has_c2c3 = 0, has_cp949 = 0;
        int cls = classify_string(sp, slen, &highbyte, &has_c2c3, &has_cp949);
        if (cls == 0) continue;  // 코드/바이너리

        if (cls == 2) {
            // 하이바이트 포함 = 잠재적 한글
            long ksc = InterlockedIncrement(&prev_korean_cmds_found);
            if (ksc <= 50) {
                write_log("[RegScan K#%ld] %s=%p len=%d hi=%d c2c3=%d cp949=%d\n",
                          ksc, reg_names[ri], (void*)val, slen,
                          highbyte, has_c2c3, has_cp949);
                dump_string(sp, slen, 120);
            }
        } else {
            // 순수 ASCII: 처음 5개만 로그 (노이즈 최소화)
            long tsc = InterlockedIncrement(&prev_text_cmds_found);
            if (tsc <= 5) {
                char txt[80];
                int tp = 0;
                int show = slen < 70 ? slen : 70;
                for (int j = 0; j < show; j++)
                    txt[tp++] = (sp[j] >= 0x20 && sp[j] < 0x7F) ? (char)sp[j] : '.';
                txt[tp] = 0;
                write_log("[RegScan A#%ld] %s=%p len=%d text: %s\n",
                          tsc, reg_names[ri], (void*)val, slen, txt);
            }
        }
        break;
    }

    // --- 호출자 스택 스캔 (한글 미발견 시 계속) ---
    if (ret_addr_ptr && !IsBadReadPtr(ret_addr_ptr, 8) && prev_korean_cmds_found <= 50) {
        uint64_t* caller_stack = ret_addr_ptr + 1;
        if (!IsBadReadPtr(caller_stack, 64)) {
            for (int si = 0; si < 8; si++) {
                uint64_t val = caller_stack[si];
                if (val < 0x10000 || val > 0x7FFFFFFFFFFF) continue;
                if (IsBadReadPtr((void*)val, 4)) continue;

                unsigned char* sp = (unsigned char*)val;
                int slen = 0;
                while (slen < 300 && !IsBadReadPtr(sp + slen, 1) && sp[slen] != 0)
                    slen++;
                if (slen < 4) continue;

                int highbyte = 0, has_c2c3 = 0, has_cp949 = 0;
                int cls = classify_string(sp, slen, &highbyte, &has_c2c3, &has_cp949);
                if (cls == 0) continue;

                if (cls == 2) {
                    long ksc = InterlockedIncrement(&prev_korean_cmds_found);
                    if (ksc <= 50) {
                        write_log("[StkScan K#%ld] stk[%d]=%p len=%d hi=%d c2c3=%d cp949=%d\n",
                                  ksc, si, (void*)val, slen,
                                  highbyte, has_c2c3, has_cp949);
                        dump_string(sp, slen, 120);
                    }
                } else {
                    long tsc = InterlockedIncrement(&prev_text_cmds_found);
                    if (tsc <= 5) {
                        char txt[80];
                        int tp = 0;
                        int show = slen < 70 ? slen : 70;
                        for (int j = 0; j < show; j++)
                            txt[tp++] = (sp[j] >= 0x20 && sp[j] < 0x7F) ? (char)sp[j] : '.';
                        txt[tp] = 0;
                        write_log("[StkScan A#%ld] stk[%d]=%p len=%d text: %s\n",
                                  tsc, si, (void*)val, slen, txt);
                    }
                }
                break;
            }
        }
    }

    return size;
}

// Post-hook: nk_command_buffer_push의 ret 후 실행됨 (모든 push)
// rax = push 반환값 (커맨드 포인터) → pending_text_cmd에 저장
// 레지스터/플래그 변경 최소화 후 원래 호출자로 점프
//
// GCC naked 함수의 "m" 오퍼랜드가 잘못된 RIP-relative 주소를 생성하여
// 크래시를 유발하므로, 동적 머신코드 트램폴린으로 대체.
// VirtualAlloc으로 실행 가능 메모리를 할당하고 절대주소를 하드코딩.
static void* build_post_hook_trampoline(void) {
    void* mem = VirtualAlloc(NULL, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!mem) return NULL;

    uint8_t* p = (uint8_t*)mem;
    int i = 0;

    // push rcx (scratch register 보존)
    p[i++] = 0x51;

    // movabs rcx, &pending_text_cmd
    p[i++] = 0x48; p[i++] = 0xB9;
    *(uint64_t*)(p + i) = (uint64_t)&pending_text_cmd;
    i += 8;

    // mov [rcx], rax (pending_text_cmd = rax = 커맨드 포인터)
    p[i++] = 0x48; p[i++] = 0x89; p[i++] = 0x01;

    // 진단: rax를 별도 변수에도 저장 (주소 불일치 검증)
    // movabs rcx, &post_hook_diag_rax
    p[i++] = 0x48; p[i++] = 0xB9;
    *(uint64_t*)(p + i) = (uint64_t)&post_hook_diag_rax;
    i += 8;
    // mov [rcx], rax
    p[i++] = 0x48; p[i++] = 0x89; p[i++] = 0x01;

    // movabs rcx, &nk_post_hook_fire_count
    p[i++] = 0x48; p[i++] = 0xB9;
    *(uint64_t*)(p + i) = (uint64_t)&nk_post_hook_fire_count;
    i += 8;

    // lock inc dword [rcx]
    p[i++] = 0xF0; p[i++] = 0xFF; p[i++] = 0x01;

    // movabs rcx, &saved_push_return_addr
    p[i++] = 0x48; p[i++] = 0xB9;
    *(uint64_t*)(p + i) = (uint64_t)&saved_push_return_addr;
    i += 8;

    // mov rcx, [rcx] (rcx = 원래 리턴 주소)
    p[i++] = 0x48; p[i++] = 0x8B; p[i++] = 0x09;

    // xchg [rsp], rcx (스택에 리턴주소 넣고, rcx 복원)
    p[i++] = 0x48; p[i++] = 0x87; p[i++] = 0x0C; p[i++] = 0x24;

    // ret (원래 호출자로 복귀)
    p[i++] = 0xC3;

    write_log("[NK Push] Post-hook trampoline built at %p (%d bytes)\n", mem, i);
    write_log("[NK Addr] &pending_text_cmd=%p (trampoline embeds)\n", &pending_text_cmd);
    write_log("[NK Addr] &post_hook_diag_rax=%p (trampoline embeds)\n", &post_hook_diag_rax);
    return mem;
}

// 동적 머신코드 naked 래퍼
// GCC naked 함수의 "m" 오퍼랜드가 잘못된 RIP-relative 주소를 생성하여
// 원본 함수 트램폴린 대신 엉뚱한 곳으로 점프하는 버그 방지.
// VirtualAlloc으로 실행 가능 메모리를 할당하고 모든 주소를 절대주소로 하드코딩.
//
// Entry: RSP ≡ 8 (mod 16), rcx=buf, edx=type, r8=size, r9=...
// 1) volatile 레지스터 저장 (7 pushes + shadow space)
// 2) handler(type, size, ret_addr_ptr) 호출
// 3) 레지스터 복원
// 4) 원본 함수 트램폴린으로 절대주소 점프
static void* build_naked_wrapper(uint64_t handler_addr, uint64_t trampoline_addr) {
    void* mem = VirtualAlloc(NULL, 256, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!mem) return NULL;

    uint8_t* p = (uint8_t*)mem;
    int i = 0;

    // --- 비휘발 레지스터를 글로벌 배열에 저장 ---
    // 호출자(인라인된 nk_draw_text)의 text 포인터 탐색용
    // rax를 임시로 사용 (어차피 trampoline prologue가 덮어씀)
    // push rax (임시 보존)
    p[i++] = 0x50;
    // movabs rax, &saved_nonvol_regs
    p[i++] = 0x48; p[i++] = 0xB8;
    *(uint64_t*)(p + i) = (uint64_t)&saved_nonvol_regs;
    i += 8;
    // mov [rax+0x00], rbx
    p[i++] = 0x48; p[i++] = 0x89; p[i++] = 0x18;
    // mov [rax+0x08], rsi
    p[i++] = 0x48; p[i++] = 0x89; p[i++] = 0x70; p[i++] = 0x08;
    // mov [rax+0x10], rdi
    p[i++] = 0x48; p[i++] = 0x89; p[i++] = 0x78; p[i++] = 0x10;
    // mov [rax+0x18], rbp
    p[i++] = 0x48; p[i++] = 0x89; p[i++] = 0x68; p[i++] = 0x18;
    // mov [rax+0x20], r12
    p[i++] = 0x4C; p[i++] = 0x89; p[i++] = 0x60; p[i++] = 0x20;
    // mov [rax+0x28], r13
    p[i++] = 0x4C; p[i++] = 0x89; p[i++] = 0x68; p[i++] = 0x28;
    // mov [rax+0x30], r14
    p[i++] = 0x4C; p[i++] = 0x89; p[i++] = 0x70; p[i++] = 0x30;
    // mov [rax+0x38], r15
    p[i++] = 0x4C; p[i++] = 0x89; p[i++] = 0x78; p[i++] = 0x38;
    // pop rax (복원)
    p[i++] = 0x58;

    // --- volatile 레지스터 저장 ---
    p[i++] = 0x51;                           // push rcx
    p[i++] = 0x52;                           // push rdx
    p[i++] = 0x41; p[i++] = 0x50;           // push r8
    p[i++] = 0x41; p[i++] = 0x51;           // push r9
    p[i++] = 0x50;                           // push rax
    p[i++] = 0x41; p[i++] = 0x52;           // push r10
    p[i++] = 0x41; p[i++] = 0x53;           // push r11
    p[i++] = 0x48; p[i++] = 0x83; p[i++] = 0xEC; p[i++] = 0x20; // sub rsp, 0x20

    // Stack layout: [rsp+0x00..0x1F] shadow
    // [rsp+0x20]=r11 [rsp+0x28]=r10 [rsp+0x30]=rax [rsp+0x38]=r9
    // [rsp+0x40]=r8(size) [rsp+0x48]=rdx(type) [rsp+0x50]=rcx(buf)
    // [rsp+0x58]=return_addr

    // --- handler(type, size, ret_addr_ptr, buf) 인자 설정 ---
    // mov ecx, [rsp+0x48]  (type from saved rdx)
    p[i++] = 0x8B; p[i++] = 0x4C; p[i++] = 0x24; p[i++] = 0x48;
    // mov rdx, [rsp+0x40]  (size from saved r8)
    p[i++] = 0x48; p[i++] = 0x8B; p[i++] = 0x54; p[i++] = 0x24; p[i++] = 0x40;
    // lea r8, [rsp+0x58]   (pointer to return_addr on stack)
    p[i++] = 0x4C; p[i++] = 0x8D; p[i++] = 0x44; p[i++] = 0x24; p[i++] = 0x58;
    // mov r9, [rsp+0x50]   (buf from saved rcx)
    p[i++] = 0x4C; p[i++] = 0x8B; p[i++] = 0x4C; p[i++] = 0x24; p[i++] = 0x50;

    // --- call nk_push_handler (절대주소) ---
    // movabs rax, handler_addr
    p[i++] = 0x48; p[i++] = 0xB8;
    *(uint64_t*)(p + i) = handler_addr;
    i += 8;
    // call rax
    p[i++] = 0xFF; p[i++] = 0xD0;

    // --- handler 반환값(new size) → saved r8 위치에 저장 ---
    // mov [rsp+0x40], rax
    p[i++] = 0x48; p[i++] = 0x89; p[i++] = 0x44; p[i++] = 0x24; p[i++] = 0x40;

    // --- 레지스터 복원 ---
    p[i++] = 0x48; p[i++] = 0x83; p[i++] = 0xC4; p[i++] = 0x20; // add rsp, 0x20
    p[i++] = 0x41; p[i++] = 0x5B;           // pop r11
    p[i++] = 0x41; p[i++] = 0x5A;           // pop r10
    p[i++] = 0x58;                           // pop rax (원본 rax - prologue가 덮어씀)
    p[i++] = 0x41; p[i++] = 0x59;           // pop r9
    p[i++] = 0x41; p[i++] = 0x58;           // pop r8  (← handler가 반환한 new size)
    p[i++] = 0x5A;                           // pop rdx
    p[i++] = 0x59;                           // pop rcx

    // --- 원본 함수 트램폴린으로 절대주소 점프 ---
    // rax는 prologue의 "mov rax, rsp"가 즉시 덮어쓰므로 사용 가능
    // movabs rax, trampoline_addr
    p[i++] = 0x48; p[i++] = 0xB8;
    *(uint64_t*)(p + i) = trampoline_addr;
    i += 8;
    // jmp rax
    p[i++] = 0xFF; p[i++] = 0xE0;

    write_log("[NK Push] Dynamic naked wrapper built at %p (%d bytes)\n", mem, i);
    write_log("[NK Push] Handler addr: %p, Trampoline addr: %p\n",
              (void*)handler_addr, (void*)trampoline_addr);
    return mem;
}

/**
 * nk_command_buffer_push 할당 훅 설치
 *
 * 15바이트 프롤로그를 14바이트 jmp + 1 NOP으로 교체
 */
static BOOL install_nk_push_hook(void) {
    if (nk_push_hook_active) return TRUE;

    void* func_addr = (void*)((uintptr_t)nwmain_base + NK_CMD_BUF_PUSH_RVA);
    uint8_t* bytes = (uint8_t*)func_addr;

    write_log("[NK Push] nk_command_buffer_push at: %p (RVA 0x%08x)\n",
              func_addr, NK_CMD_BUF_PUSH_RVA);

    // 프롤로그 검증
    if (memcmp(bytes, NK_PUSH_EXPECTED_PROLOGUE, NK_PUSH_HOOK_SIZE) != 0) {
        write_log("[NK Push] ERROR: Prologue mismatch\n");
        write_log("[NK Push] Got: ");
        for (int i = 0; i < NK_PUSH_HOOK_SIZE; i++)
            write_log("%02x ", bytes[i]);
        write_log("\n");
        return FALSE;
    }

    write_log("[NK Push] Prologue verified\n");

    // 트램폴린 생성: 원본 15바이트 + jmp [rip+0] + 8바이트 주소
    nk_push_trampoline = VirtualAlloc(NULL, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!nk_push_trampoline) {
        write_log("[NK Push] ERROR: VirtualAlloc failed\n");
        return FALSE;
    }

    uint8_t* tramp = (uint8_t*)nk_push_trampoline;
    memcpy(tramp, func_addr, NK_PUSH_HOOK_SIZE);

    // jmp [rip+0] → func_addr + 15
    tramp[NK_PUSH_HOOK_SIZE + 0] = 0xFF;
    tramp[NK_PUSH_HOOK_SIZE + 1] = 0x25;
    tramp[NK_PUSH_HOOK_SIZE + 2] = 0x00;
    tramp[NK_PUSH_HOOK_SIZE + 3] = 0x00;
    tramp[NK_PUSH_HOOK_SIZE + 4] = 0x00;
    tramp[NK_PUSH_HOOK_SIZE + 5] = 0x00;
    *(uint64_t*)(tramp + NK_PUSH_HOOK_SIZE + 6) = (uint64_t)func_addr + NK_PUSH_HOOK_SIZE;

    original_nk_cmd_buf_push = nk_push_trampoline;

    // Post-hook 동적 머신코드 트램폴린 생성
    nk_push_post_hook_addr = build_post_hook_trampoline();
    if (!nk_push_post_hook_addr) {
        write_log("[NK Push] WARNING: Post-hook trampoline build failed\n");
    }

    // 동적 머신코드 naked 래퍼 생성
    // GCC naked 함수의 "m" 오퍼랜드 버그를 완전히 제거
    void* naked_wrapper = build_naked_wrapper(
        (uint64_t)nk_push_handler,
        (uint64_t)nk_push_trampoline
    );
    if (!naked_wrapper) {
        write_log("[NK Push] ERROR: Naked wrapper build failed\n");
        return FALSE;
    }

    // 원본 함수 패치: 14바이트 jmp + 1 NOP = 15바이트
    DWORD old_protect;
    if (!VirtualProtect(func_addr, NK_PUSH_HOOK_SIZE, PAGE_EXECUTE_READWRITE, &old_protect)) {
        write_log("[NK Push] ERROR: VirtualProtect failed (error %d)\n", GetLastError());
        VirtualFree(nk_push_trampoline, 0, MEM_RELEASE);
        return FALSE;
    }

    uint8_t* hook = (uint8_t*)func_addr;
    hook[0] = 0xFF;  // jmp [rip+0]
    hook[1] = 0x25;
    hook[2] = 0x00;
    hook[3] = 0x00;
    hook[4] = 0x00;
    hook[5] = 0x00;
    *(uint64_t*)(hook + 6) = (uint64_t)naked_wrapper;
    hook[14] = 0x90;  // NOP (15번째 바이트)

    VirtualProtect(func_addr, NK_PUSH_HOOK_SIZE, old_protect, &old_protect);

    nk_push_hook_active = 1;
    write_log("[NK Push] Hook installed (with return-address hijacking)!\n");
    write_log("[NK Push] Wrapper: %p, Trampoline: %p, PostHook: %p\n",
              naked_wrapper, nk_push_trampoline, nk_push_post_hook_addr);

    return TRUE;
}

// ============================================================================
// Phase 4 - Stage 2: nk_draw_text 전체 레지스터/스택 진단 훅
//
// RVA 0x952A10 - NK_COMMAND_TEXT를 생성하는 함수 (nk_draw_text)
// 이 함수 내에서 nk_command_buffer_push(edx=0x10)를 호출함
//
// 프롤로그 18바이트:
//   48 8B C4                mov rax, rsp
//   55                      push rbp
//   57                      push rdi
//   41 54                   push r12
//   41 56                   push r14
//   41 57                   push r15
//   48 8D A8 B8 FD FF FF   lea rbp, [rax-0x248]
// ============================================================================

static const uint8_t NK_DRAW_TEXT_EXPECTED_PROLOGUE[] = {
    0x48, 0x8B, 0xC4,              // mov rax, rsp
    0x55,                           // push rbp
    0x57,                           // push rdi
    0x41, 0x54,                     // push r12
    0x41, 0x56,                     // push r14
    0x41, 0x57,                     // push r15
    0x48, 0x8D, 0xA8, 0xB8, 0xFD, 0xFF, 0xFF  // lea rbp, [rax-0x248]
};
#define NK_DRAW_TEXT_HOOK_SIZE 18

static void* nk_draw_text_trampoline = NULL;
static void* original_nk_draw_text = NULL;
static volatile int nk_draw_text_hook_active = 0;

// 진단용: naked 래퍼에서 원본 rsp를 저장
static volatile uint64_t nk_diag_orig_rsp = 0;

// C 핸들러 - 전체 레지스터 + 스택 덤프
int nk_draw_text_handler(uint64_t p1, uint64_t p2, uint64_t p3, uint64_t p4);

int nk_draw_text_handler(uint64_t p1, uint64_t p2, uint64_t p3, uint64_t p4) {
    long count = InterlockedIncrement(&nk_total_calls);

    if (count <= 50) {
        uint64_t orig_rsp = nk_diag_orig_rsp;
        write_log("[NK DrawText #%ld] rcx=%016llx rdx=%016llx r8=%016llx r9=%016llx\n",
                  count, p1, p2, p3, p4);

        // 원본 스택에서 추가 파라미터 읽기
        if (orig_rsp && !IsBadReadPtr((void*)orig_rsp, 0x60)) {
            uint64_t* stk = (uint64_t*)orig_rsp;
            write_log("[NK DrawText #%ld] stk: ret=%016llx +28=%016llx +30=%016llx +38=%016llx +40=%016llx +48=%016llx\n",
                      count, stk[0], stk[5], stk[6], stk[7], stk[8], stk[9]);
        }

        // 각 레지스터 값이 유효한 문자열 포인터인지 확인
        uint64_t candidates[] = {p1, p2, p3, p4};
        const char* names[] = {"rcx", "rdx", "r8", "r9"};
        for (int i = 0; i < 4; i++) {
            if (candidates[i] > 0x10000 && candidates[i] < 0x7FFFFFFFFFFF &&
                !IsBadReadPtr((void*)candidates[i], 4)) {
                unsigned char* ptr = (unsigned char*)candidates[i];
                if ((ptr[0] >= 0x20 && ptr[0] < 0x7F) || ptr[0] >= 0xC0) {
                    int dump_len = 0;
                    while (dump_len < 64 && !IsBadReadPtr(ptr + dump_len, 1) && ptr[dump_len] != 0)
                        dump_len++;
                    if (dump_len > 0) {
                        char hex[200];
                        int hp = 0;
                        int show = dump_len < 32 ? dump_len : 32;
                        for (int j = 0; j < show && hp < 190; j++)
                            hp += sprintf(hex + hp, "%02x ", ptr[j]);
                        write_log("[NK DrawText #%ld] %s -> TEXT(%d): hex=%s\n",
                                  count, names[i], dump_len, hex);
                    }
                }
            }
        }

        // 스택 값도 문자열 포인터인지 확인
        if (orig_rsp && !IsBadReadPtr((void*)orig_rsp, 0x60)) {
            uint64_t* stk = (uint64_t*)orig_rsp;
            for (int si = 5; si <= 9; si++) {
                uint64_t val = stk[si];
                if (val > 0x10000 && val < 0x7FFFFFFFFFFF &&
                    !IsBadReadPtr((void*)val, 4)) {
                    unsigned char* ptr = (unsigned char*)val;
                    if ((ptr[0] >= 0x20 && ptr[0] < 0x7F) || ptr[0] >= 0xC0) {
                        int dump_len = 0;
                        while (dump_len < 64 && !IsBadReadPtr(ptr + dump_len, 1) && ptr[dump_len] != 0)
                            dump_len++;
                        if (dump_len > 0) {
                            char hex[200];
                            int hp = 0;
                            int show = dump_len < 32 ? dump_len : 32;
                            for (int j = 0; j < show && hp < 190; j++)
                                hp += sprintf(hex + hp, "%02x ", ptr[j]);
                            write_log("[NK DrawText #%ld] stk+%02x -> TEXT(%d): hex=%s\n",
                                      count, si * 8, dump_len, hex);
                        }
                    }
                }
            }
        }
    }

    return 0;  // passthrough
}

// Naked 어셈블리 래퍼 - 전체 레지스터 보존 + 진단
__attribute__((naked))
static void my_nk_draw_text_naked(void) {
    __asm__ volatile (
        // 원본 rsp 저장 (글로벌 변수에)
        "movq %%rsp, %[orig_rsp]\n"

        // volatile 레지스터 저장
        "push %%rcx\n"
        "push %%rdx\n"
        "push %%r8\n"
        "push %%r9\n"
        "push %%rax\n"
        "push %%r10\n"
        "push %%r11\n"
        "sub $0x20, %%rsp\n"   // shadow space

        // handler(rcx, rdx, r8, r9) - 원본 레지스터 값 전달
        // 7 pushes + sub 0x20 = 0x58 offset
        "mov 0x50(%%rsp), %%rcx\n"   // saved rcx
        "mov 0x48(%%rsp), %%rdx\n"   // saved rdx
        "mov 0x40(%%rsp), %%r8\n"    // saved r8
        "mov 0x38(%%rsp), %%r9\n"    // saved r9
        "call nk_draw_text_handler\n"

        // 레지스터 복원
        "add $0x20, %%rsp\n"
        "pop %%r11\n"
        "pop %%r10\n"
        "pop %%rax\n"
        "pop %%r9\n"
        "pop %%r8\n"
        "pop %%rdx\n"
        "pop %%rcx\n"

        // 트램폴린으로 (원본 18바이트 프롤로그 실행 후 원래 함수 본체로)
        "jmp *%[orig]\n"

        :
        : [orig] "m"(original_nk_draw_text),
          [orig_rsp] "m"(nk_diag_orig_rsp)
        :
    );
}

/**
 * nk_draw_text 훅 설치
 *
 * 18바이트 프롤로그를 jmp [rip+0] (14바이트) + NOP x4로 교체
 */
static BOOL install_nk_draw_text_hook(void) {
    if (nk_draw_text_hook_active) return TRUE;

    void* func_addr = (void*)((uintptr_t)nwmain_base + NK_DRAW_TEXT_RVA);
    uint8_t* bytes = (uint8_t*)func_addr;

    write_log("[NK DrawText] nk_draw_text at: %p (RVA 0x%08x)\n",
              func_addr, NK_DRAW_TEXT_RVA);

    // 프롤로그 검증
    if (memcmp(bytes, NK_DRAW_TEXT_EXPECTED_PROLOGUE, NK_DRAW_TEXT_HOOK_SIZE) != 0) {
        write_log("[NK DrawText] ERROR: Prologue mismatch\n");
        write_log("[NK DrawText] Expected: ");
        for (int i = 0; i < NK_DRAW_TEXT_HOOK_SIZE; i++)
            write_log("%02x ", NK_DRAW_TEXT_EXPECTED_PROLOGUE[i]);
        write_log("\n[NK DrawText] Got:      ");
        for (int i = 0; i < NK_DRAW_TEXT_HOOK_SIZE; i++)
            write_log("%02x ", bytes[i]);
        write_log("\n");
        return FALSE;
    }

    write_log("[NK DrawText] Prologue verified (%d bytes)\n", NK_DRAW_TEXT_HOOK_SIZE);

    // 트램폴린: 원본 18바이트 + jmp [rip+0] (6) + 8바이트 주소
    nk_draw_text_trampoline = VirtualAlloc(NULL, 64,
        MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!nk_draw_text_trampoline) {
        write_log("[NK DrawText] ERROR: VirtualAlloc failed\n");
        return FALSE;
    }

    uint8_t* tramp = (uint8_t*)nk_draw_text_trampoline;
    memcpy(tramp, func_addr, NK_DRAW_TEXT_HOOK_SIZE);

    // jmp [rip+0] → func_addr + 18
    tramp[NK_DRAW_TEXT_HOOK_SIZE + 0] = 0xFF;
    tramp[NK_DRAW_TEXT_HOOK_SIZE + 1] = 0x25;
    tramp[NK_DRAW_TEXT_HOOK_SIZE + 2] = 0x00;
    tramp[NK_DRAW_TEXT_HOOK_SIZE + 3] = 0x00;
    tramp[NK_DRAW_TEXT_HOOK_SIZE + 4] = 0x00;
    tramp[NK_DRAW_TEXT_HOOK_SIZE + 5] = 0x00;
    *(uint64_t*)(tramp + NK_DRAW_TEXT_HOOK_SIZE + 6) =
        (uint64_t)func_addr + NK_DRAW_TEXT_HOOK_SIZE;

    original_nk_draw_text = nk_draw_text_trampoline;

    // 원본 함수 패치: jmp [rip+0] (14바이트) + NOP x4 = 18바이트
    DWORD old_protect;
    if (!VirtualProtect(func_addr, NK_DRAW_TEXT_HOOK_SIZE,
                        PAGE_EXECUTE_READWRITE, &old_protect)) {
        write_log("[NK DrawText] ERROR: VirtualProtect failed (error %d)\n",
                  GetLastError());
        VirtualFree(nk_draw_text_trampoline, 0, MEM_RELEASE);
        return FALSE;
    }

    uint8_t* hook = (uint8_t*)func_addr;
    hook[0] = 0xFF;  // jmp [rip+0]
    hook[1] = 0x25;
    hook[2] = 0x00;
    hook[3] = 0x00;
    hook[4] = 0x00;
    hook[5] = 0x00;
    *(uint64_t*)(hook + 6) = (uint64_t)my_nk_draw_text_naked;
    hook[14] = 0x90;  // NOP x4
    hook[15] = 0x90;
    hook[16] = 0x90;
    hook[17] = 0x90;

    VirtualProtect(func_addr, NK_DRAW_TEXT_HOOK_SIZE, old_protect, &old_protect);

    nk_draw_text_hook_active = 1;
    write_log("[NK DrawText] Hook installed!\n");
    write_log("[NK DrawText] Naked: %p, Trampoline: %p\n",
              my_nk_draw_text_naked, nk_draw_text_trampoline);

    return TRUE;
}

// ============================================================================
// Phase 4 - New Approach: nk_user_font->width 콜백 훅
// ============================================================================
//
// Nuklear 텍스트 처리 파이프라인:
//   1. Layout (폭 계산): font->width(userdata, height, text, len)  ← 여기를 훅!
//   2. Command Generation: nk_draw_text (인라인됨 - 직접 훅 불가)
//   3. Rendering: nk_convert → nk_draw_list_add_text
//
// width 콜백은 함수 포인터이므로 MSVC 인라이닝 불가능.
// 텍스트(text)와 길이(len)가 직접 파라미터로 전달됨.
//
// nk_user_font 구조체 레이아웃 (x64):
//   offset 0x00: nk_handle userdata (8 bytes)
//   offset 0x08: float height (4 bytes + 4 padding)
//   offset 0x10: nk_text_width_f width (8 bytes, function pointer)
//   offset 0x18: nk_query_font_glyph_f query (8 bytes, function pointer)
//   offset 0x20: nk_handle texture (8 bytes)
//
// Windows x64 ABI for width callback:
//   rcx = nk_handle userdata (8 bytes)
//   xmm1 = float height (rdx slot wasted)
//   r8 = const char* text
//   r9d = int len
//   return: float in xmm0

/**
 * nwmain.exe 이미지 크기 가져오기
 */
static SIZE_T get_nwmain_image_size(void) {
    MODULEINFO mi;
    if (GetModuleInformation(GetCurrentProcess(), nwmain_base, &mi, sizeof(mi))) {
        return mi.SizeOfImage;
    }
    return 0;
}

/**
 * nk_user_font->width 콜백 훅 함수 (진단 + 변환)
 *
 * 텍스트에 비ASCII 바이트가 있으면 로그 기록.
 * Latin-1 손상된 CP949 또는 raw CP949 감지 시 UTF-8로 변환 후 원본 호출.
 */
static float my_nk_width_callback(void* userdata, float height, const char* text, int len) {
    InterlockedIncrement(&nk_width_total_calls);

    if (!text || len <= 0 || !original_nk_width_fn) {
        return original_nk_width_fn ? original_nk_width_fn(userdata, height, text, len) : 0.0f;
    }

    // 비ASCII 바이트 검사
    int has_highbyte = 0;
    for (int i = 0; i < len; i++) {
        if ((unsigned char)text[i] >= 0x80) {
            has_highbyte = 1;
            break;
        }
    }

    // 변환 시도 + in-place 수정 (비ASCII 텍스트만)
    if (has_highbyte) {
        char local_buf[4096];
        int converted_len = nk_process_text(text, len, local_buf, sizeof(local_buf));
        if (converted_len > 0 && converted_len <= len) {
            InterlockedIncrement(&nk_conversion_count);

            // 진단 로깅 (처음 10개만)
            if (nk_width_log_count < 10) {
                nk_width_log_count++;
                char hex_before[256], hex_after[256];
                int hb = 0, ha = 0;
                int show = len < 30 ? len : 30;
                for (int i = 0; i < show && hb < 250; i++)
                    hb += sprintf(hex_before + hb, "%02x ", (unsigned char)text[i]);
                hex_before[hb] = 0;
                show = converted_len < 30 ? converted_len : 30;
                for (int i = 0; i < show && ha < 250; i++)
                    ha += sprintf(hex_after + ha, "%02x ", (unsigned char)local_buf[i]);
                hex_after[ha] = 0;
                write_log("[NK Conv #%d] h=%.1f len=%d->%d\n  before: %s\n  after:  %s\n",
                          nk_width_log_count, height, len, converted_len,
                          hex_before, hex_after);
            }

            // In-place 텍스트 수정: 렌더링 단계에서도 변환된 텍스트를 사용하게 됨
            // Latin-1 corrupted (4바이트/글자) → UTF-8 한글 (3바이트/글자)이므로 항상 짧아짐
            memcpy((char*)text, local_buf, converted_len);
            // 나머지를 null로 패딩 (렌더링 시 글리프0 = 빈 글리프)
            if (converted_len < len) {
                memset((char*)text + converted_len, 0, len - converted_len);
            }

            return original_nk_width_fn(userdata, height, text, converted_len);
        }

        // 변환 실패 시 로그
        if (nk_width_log_count < 10) {
            nk_width_log_count++;
            char hex[256];
            int hp = 0;
            int show = len < 30 ? len : 30;
            for (int i = 0; i < show && hp < 250; i++)
                hp += sprintf(hex + hp, "%02x ", (unsigned char)text[i]);
            hex[hp] = 0;
            write_log("[NK Width #%d] h=%.1f len=%d UNCONVERTED: %s\n",
                      nk_width_log_count, height, len, hex);
        }
    }

    return original_nk_width_fn(userdata, height, text, len);
}

/**
 * 안전한 메모리 읽기 (ReadProcessMemory 사용)
 *
 * VirtualQuery와 실제 읽기 사이 타이밍 문제로 ACCESS_VIOLATION 방지.
 */
static int safe_read(const void* addr, void* buf, size_t size) {
    SIZE_T read_bytes = 0;
    return ReadProcessMemory(GetCurrentProcess(), addr, buf, size, &read_bytes)
           && read_bytes == size;
}

/**
 * 프로세스 메모리에서 nk_user_font 구조체 스캔
 *
 * 매칭 조건 (베이크 높이 의존 제거):
 *   1. offset 0x08: float > 0, < 100, not NaN (합리적 폰트 높이)
 *   2. offset 0x10: nwmain.exe 실행 코드 포인터 (width 콜백)
 *   3. offset 0x18: nwmain.exe 실행 코드 포인터 (query 콜백)
 *   4. offset 0x20: 작은 정수 < 1000 (texture handle/ID)
 *   5. 힙 메모리에 위치 (MEM_PRIVATE)
 *
 * ReadProcessMemory로 안전한 메모리 읽기 (크래시 방지).
 *
 * @return 발견된 후보 수
 */
static int scan_for_nk_user_font(void) {
    uintptr_t nw_base = (uintptr_t)nwmain_base;
    SIZE_T nw_size = get_nwmain_image_size();
    if (!nw_size) {
        write_log("[NK Scan] ERROR: Cannot get nwmain image size\n");
        return 0;
    }

    write_log("[NK Scan] nwmain range: %p - %p (size 0x%llx)\n",
              (void*)nw_base, (void*)(nw_base + nw_size), (unsigned long long)nw_size);

    int found = 0;
    int candidates_logged = 0;
    MEMORY_BASIC_INFORMATION mbi;
    HANDLE self = GetCurrentProcess();
    uintptr_t addr = 0x10000;

    while (VirtualQuery((void*)addr, &mbi, sizeof(mbi))) {
        uintptr_t region_base = (uintptr_t)mbi.BaseAddress;
        uintptr_t region_end = region_base + mbi.RegionSize;

        // committed + readable + private(힙) 메모리만 스캔
        // MEM_IMAGE(DLL/EXE)와 MEM_MAPPED는 제외 → false positive 및 크래시 감소
        if (mbi.State == MEM_COMMIT &&
            mbi.Type == MEM_PRIVATE &&
            (mbi.Protect & (PAGE_READONLY | PAGE_READWRITE)) &&
            !(mbi.Protect & (PAGE_GUARD | PAGE_NOACCESS))) {

            if (mbi.RegionSize >= 40) {
                // 구조체 40바이트를 한번에 읽어서 검사 (ReadProcessMemory 호출 최소화)
                for (uintptr_t p = region_base; p + 40 <= region_end; p += 8) {
                    uint8_t buf[40];
                    if (!safe_read((void*)p, buf, 40)) break;  // 영역 읽기 실패 시 다음 영역

                    // offset 0x08: float height (합리적 폰트 높이: 5~50)
                    float h;
                    memcpy(&h, buf + 0x08, sizeof(float));
                    if (!(h >= 5.0f && h <= 50.0f)) continue;  // 0, NaN, 극단값 제거

                    // offset 0x10: width 함수 포인터
                    uint64_t width_ptr;
                    memcpy(&width_ptr, buf + 0x10, sizeof(uint64_t));
                    if (width_ptr < nw_base || width_ptr >= nw_base + nw_size) continue;

                    // offset 0x18: query 함수 포인터
                    uint64_t query_ptr;
                    memcpy(&query_ptr, buf + 0x18, sizeof(uint64_t));
                    if (query_ptr < nw_base || query_ptr >= nw_base + nw_size) continue;

                    // offset 0x20: texture handle (양수 정수여야 함, 0은 미초기화)
                    uint64_t texture;
                    memcpy(&texture, buf + 0x20, sizeof(uint64_t));
                    if (texture == 0 || texture > 1000) continue;

                    // width와 query가 서로 다른 함수여야 함
                    if (width_ptr == query_ptr) continue;

                    // width 함수 프롤로그 검증: 실제 코드인지 확인
                    // 유효한 x64 함수 프롤로그 첫 바이트:
                    //   0x48 (REX.W prefix), 0x40-0x41 (REX), 0x55 (push rbp),
                    //   0x53 (push rbx), 0x56 (push rsi), 0x57 (push rdi)
                    uint8_t prologue_byte;
                    if (!safe_read((void*)width_ptr, &prologue_byte, 1)) continue;
                    if (!(prologue_byte == 0x48 || prologue_byte == 0x40 ||
                          prologue_byte == 0x41 || prologue_byte == 0x55 ||
                          prologue_byte == 0x53 || prologue_byte == 0x56 ||
                          prologue_byte == 0x57)) continue;

                    // 후보 발견!
                    uint64_t userdata;
                    memcpy(&userdata, buf + 0x00, sizeof(uint64_t));

                    if (candidates_logged < 20) {
                        write_log("[NK Scan] MATCH at %p: ud=%016llx h=%.1f w=%p q=%p tex=%llu\n",
                                  (void*)p, (unsigned long long)userdata, h,
                                  (void*)width_ptr, (void*)query_ptr,
                                  (unsigned long long)texture);

                        // width 함수 프롤로그 덤프
                        uint8_t code[16];
                        if (safe_read((void*)width_ptr, code, 16)) {
                            write_log("  width prologue: ");
                            for (int i = 0; i < 16; i++)
                                write_log("%02x ", code[i]);
                            write_log("\n");
                        }
                        candidates_logged++;
                    }

                    found++;

                    // width 훅 설치
                    if (!nk_width_hook_active) {
                        original_nk_width_fn = (nk_text_width_fn_t)width_ptr;
                        write_log("[NK Scan] Original width callback: %p (RVA 0x%llx)\n",
                                  (void*)width_ptr,
                                  (unsigned long long)(width_ptr - nw_base));

                        void** width_slot = (void**)(p + 0x10);
                        DWORD old_protect;
                        if (VirtualProtect(width_slot, 8, PAGE_READWRITE, &old_protect)) {
                            *width_slot = (void*)my_nk_width_callback;
                            VirtualProtect(width_slot, 8, old_protect, &old_protect);
                            nk_width_hook_active = 1;
                            write_log("[NK Scan] Width hook installed at struct %p\n", (void*)p);
                        } else {
                            write_log("[NK Scan] ERROR: VirtualProtect failed\n");
                        }
                    } else {
                        // 추가 폰트: 같은 원본이면 교체, 이미 교체됐으면 스킵
                        nk_text_width_fn_t cur = (nk_text_width_fn_t)width_ptr;
                        if (cur == original_nk_width_fn) {
                            void** width_slot = (void**)(p + 0x10);
                            DWORD old_protect;
                            if (VirtualProtect(width_slot, 8, PAGE_READWRITE, &old_protect)) {
                                *width_slot = (void*)my_nk_width_callback;
                                VirtualProtect(width_slot, 8, old_protect, &old_protect);
                                write_log("[NK Scan] Additional font hooked at %p\n", (void*)p);
                            }
                        }
                    }

                    if (found >= 20) goto scan_done;
                }
            }
        }

        addr = region_end;
        if (addr <= region_base) break;
    }

scan_done:
    write_log("[NK Scan] Complete: %d structs found/hooked\n", found);
    return found;
}

/**
 * nk_user_font 스캔 스레드
 *
 * 베이크 완료 후 주기적으로 메모리 스캔하여 nk_user_font 구조체 탐색.
 * 발견 시 width 콜백 교체.
 */
static DWORD WINAPI nk_font_scan_thread(LPVOID param) {
    (void)param;

    write_log("[NK FontScan] Thread started, waiting for bake completion...\n");

    // 베이크 완료 대기 (최대 60초)
    for (int i = 0; i < 600; i++) {
        if (baked_height_count > 0) break;
        Sleep(100);
    }

    if (baked_height_count == 0) {
        write_log("[NK FontScan] WARNING: No baked heights after 60s, scanning anyway\n");
    } else {
        write_log("[NK FontScan] Bake complete (%d fonts), waiting 5s for NK init...\n",
                  baked_height_count);
        Sleep(5000);  // Nuklear 초기화 대기
    }

    // 주기적 스캔 (최대 10회, 5초 간격)
    for (int attempt = 0; attempt < 10; attempt++) {
        write_log("[NK FontScan] Scan attempt %d...\n", attempt + 1);

        int found = scan_for_nk_user_font();
        if (found > 0 && nk_width_hook_active) {
            write_log("[NK FontScan] SUCCESS! Width hook active after %d attempts\n",
                      attempt + 1);
            return 0;
        }

        write_log("[NK FontScan] No match yet, retrying in 5s...\n");
        Sleep(5000);
    }

    write_log("[NK FontScan] FAILED: Could not find nk_user_font after 10 attempts\n");
    return 0;
}

// ============================================================================
// DLL 진입점
// ============================================================================

BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpvReserved) {
    (void)hinstDLL;
    (void)lpvReserved;

    if (fdwReason == DLL_PROCESS_ATTACH) {
        // 로그 초기화
        InitializeCriticalSection(&log_cs);
        InitializeCriticalSection(&nk_buffer_cs);

        FILE* log = fopen(LOG_FILE, "w");
        if (log) {
            fprintf(log, "=================================================\n");
            fprintf(log, "NWN:EE Korean Hook DLL (Windows x64) - Phase 2\n");
            fprintf(log, "=================================================\n\n");
            fclose(log);
        }

        write_log("[NWN Korean Hook] Initializing (Phase 2: Bake)...\n");

        // nwmain.exe 베이스 주소 찾기
        nwmain_base = find_nwmain_base();
        if (!nwmain_base) {
            write_log("[Hook] ERROR: Could not find nwmain.exe\n");
            return FALSE;
        }

        write_log("[Hook] nwmain.exe base: %p\n", nwmain_base);

        // Phase 2: 함수 포인터 후킹 시도
        if (!install_bake_hook()) {
            // 실패 시 지연 훅킹 스레드 시작
            write_log("[Hook] Deferred hooking - starting poll thread\n");
            CreateThread(NULL, 0, bake_hook_thread, NULL, 0, NULL);
        }

        // Phase 3: GetSymbolCoords 후킹 - 비활성화
        // advance 값이 정규화된 값이라 단순 배수 조정으로 해결 안됨
        write_log("[Hook] GetSymbolCoords hook DISABLED (need CalculateVisibleStringLengthAndWidth patch)\n");

        // Phase 4 - Stage 1/2: 비활성화 (dead end 확인)
        // nk_command_buffer_push (RVA 0xC10434): NK 텍스트 경로 아님 판명
        // nk_draw_text (RVA 0x952A10): NULL string만 수신
        write_log("[Hook] NK Push/DrawText hooks DISABLED (dead ends)\n");

        // Phase 4 - NK width 콜백 훅: 비활성화
        // width 훅으로 텍스트 감지/변환 성공했으나, 렌더링 단계에서
        // 글리프 lookup 실패 (codepoint → chardata 매핑 불명)
        // 상세: docs/NUKLEAR_ANALYSIS.md 참조
        write_log("[Hook] NK width callback hook DISABLED (glyph lookup unsolved)\n");

        write_log("\n=== Korean Hook Ready ===\n");
        write_log("Glyph range: 0-255 (base) + 256-2605 (Korean)\n");
        write_log("Mode: Bake (Phase 2)\n");
        write_log("Input encoding: CP949\n");
        write_log("\n");
    }
    else if (fdwReason == DLL_PROCESS_DETACH) {
        // 통계 로그
        write_log("\n=== Final Statistics ===\n");
        write_log("[NK] Hooks disabled (glyph lookup unsolved)\n");

        // 정리
        if (korean_chars) {
            free(korean_chars);
            korean_chars = NULL;
        }

        DeleteCriticalSection(&nk_buffer_cs);
        DeleteCriticalSection(&log_cs);
    }

    return TRUE;
}
