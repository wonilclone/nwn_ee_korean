/**
 * NWN:EE Windows x64 한글 패치 DLL
 *
 * Phase 2: AurGetTTFTexture 후킹으로 한글 글리프 베이크 (2,606개)
 * Phase 3: GetSymbolCoords 후킹으로 한글 글리프 advance width 조정
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
static AurGetTTFTexture_fn original_bake_2 = NULL;
static AurGetTTFTexture_fn original_bake_3 = NULL;
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
static int nk_debug_log_count = 0;
#define MAX_NK_DEBUG_LOG 30

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
 * Latin-1 손상된 UTF-8 → CP949 원본 복원 → UTF-8 한글 변환
 *
 * 입력: UTF-8 인코딩된 Latin-1 문자열 (원본은 CP949)
 * 출력: UTF-8 인코딩된 한글 문자열
 *
 * 과정:
 * 1. UTF-8 디코딩하여 유니코드 코드포인트 추출
 * 2. 0x80~0xFF 범위 코드포인트는 원래 CP949 바이트
 * 3. 연속된 두 바이트를 CP949로 해석하여 한글 유니코드로 변환
 * 4. UTF-8로 인코딩하여 출력
 */
static int convert_latin1_corrupted_to_utf8(const char* src, int src_len, char* dst, int dst_size) {
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
            // UTF-8 2바이트 시퀀스 (C0-DF XX)
            unsigned char b1 = (unsigned char)src[si + 1];
            if ((b1 & 0xC0) == 0x80) {
                // 유니코드 코드포인트 추출
                uint16_t cp = ((b & 0x1F) << 6) | (b1 & 0x3F);
                // Latin-1 범위 (U+0080~U+00FF)는 원래 바이트로 복원
                if (cp <= 0xFF) {
                    bytes[byte_count++] = (unsigned char)cp;
                } else {
                    // 그 외는 원본 유지
                    bytes[byte_count++] = b;
                    bytes[byte_count++] = b1;
                }
                si += 2;
            } else {
                bytes[byte_count++] = b;
                si++;
            }
        }
        else if ((b & 0xF0) == 0xE0 && si + 2 < src_len) {
            // UTF-8 3바이트 시퀀스 - 이미 한글일 수 있음, 그대로 출력
            unsigned char b1 = (unsigned char)src[si + 1];
            unsigned char b2 = (unsigned char)src[si + 2];
            if (di + 3 < dst_size) {
                dst[di++] = b;
                dst[di++] = b1;
                dst[di++] = b2;
            }
            si += 3;
            continue;  // bytes 배열 건너뜀
        }
        else {
            bytes[byte_count++] = b;
            si++;
        }
    }

    // bytes 배열을 CP949로 해석하여 UTF-8로 변환
    int bi = 0;
    while (bi < byte_count && di < dst_size - 3) {
        unsigned char b0 = bytes[bi];

        if (b0 < 0x80) {
            // ASCII
            dst[di++] = b0;
            bi++;
        }
        else if (b0 >= 0xB0 && b0 <= 0xC8 && bi + 1 < byte_count) {
            // CP949 완성형 한글 가능성
            unsigned char b1 = bytes[bi + 1];

            if (b1 >= 0xA1 && b1 <= 0xFE) {
                // CP949 → Unicode 변환
                uint32_t unicode = cp949_to_unicode(b0, b1);

                if (unicode != 0 && unicode >= 0xAC00 && unicode <= 0xD7A3) {
                    // 유효한 한글: UTF-8로 인코딩
                    dst[di++] = (char)(0xE0 | ((unicode >> 12) & 0x0F));
                    dst[di++] = (char)(0x80 | ((unicode >> 6) & 0x3F));
                    dst[di++] = (char)(0x80 | (unicode & 0x3F));
                    bi += 2;
                    continue;
                }
            }
            // 변환 실패: 원본 바이트 유지
            dst[di++] = b0;
            bi++;
        }
        else {
            // 그 외: 그대로 복사
            dst[di++] = b0;
            bi++;
        }
    }

    dst[di] = '\0';
    return di;
}

/**
 * CP949 문자열을 UTF-8로 직접 변환
 */
static int convert_cp949_to_utf8(const char* src, int src_len, char* dst, int dst_size) {
    if (!src || !dst || src_len <= 0 || dst_size <= 0) return 0;

    int si = 0;
    int di = 0;

    while (si < src_len && di < dst_size - 3) {
        unsigned char b0 = (unsigned char)src[si];

        if (b0 < 0x80) {
            // ASCII
            dst[di++] = src[si++];
        }
        else if (b0 >= 0xB0 && b0 <= 0xC8 && si + 1 < src_len) {
            unsigned char b1 = (unsigned char)src[si + 1];

            if (b1 >= 0xA1 && b1 <= 0xFE) {
                uint32_t unicode = cp949_to_unicode(b0, b1);

                if (unicode != 0 && unicode >= 0xAC00 && unicode <= 0xD7A3) {
                    dst[di++] = (char)(0xE0 | ((unicode >> 12) & 0x0F));
                    dst[di++] = (char)(0x80 | ((unicode >> 6) & 0x3F));
                    dst[di++] = (char)(0x80 | (unicode & 0x3F));
                    si += 2;
                    continue;
                }
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
    int first_non_ascii = -1;
    for (int i = 0; i < len; i++) {
        if ((unsigned char)text[i] >= 0x80) {
            has_non_ascii = 1;
            first_non_ascii = i;
            break;
        }
    }

    // 비ASCII가 없으면 변환 불필요
    if (!has_non_ascii) return 0;

    // 디버깅 로그
    if (nk_debug_log_count < MAX_NK_DEBUG_LOG) {
        write_log("[NK Debug #%d] len=%d, first_non_ascii=%d, bytes: ",
                  nk_debug_log_count, len, first_non_ascii);
        nk_debug_log_count++;
    }

    // Latin-1 손상된 UTF-8 감지 (C2/C3 XX 패턴)
    for (int i = 0; i < len - 1; i++) {
        unsigned char b0 = (unsigned char)text[i];
        unsigned char b1 = (unsigned char)text[i + 1];
        if ((b0 == 0xC2 || b0 == 0xC3) && (b1 >= 0x80 && b1 <= 0xBF)) {
            InterlockedIncrement(&nk_conversion_count);
            return convert_latin1_corrupted_to_utf8(text, len, out_buf, out_size);
        }
    }

    // 원본 CP949 감지
    for (int i = 0; i < len - 1; i++) {
        unsigned char b0 = (unsigned char)text[i];
        if (b0 >= 0xB0 && b0 <= 0xC8) {
            unsigned char b1 = (unsigned char)text[i + 1];
            if (b1 >= 0xA1 && b1 <= 0xFE) {
                InterlockedIncrement(&nk_conversion_count);
                return convert_cp949_to_utf8(text, len, out_buf, out_size);
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
// Phase 4: Nuklear nk_draw_list_add_text 래퍼
// ============================================================================

// text 파라미터 위치를 분석해야 함
// 함수 프롤로그 분석:
//   48 89 5c 24 18     mov [rsp+18h], rbx    ; 홈 영역에 rbx 저장
//   48 89 74 24 20     mov [rsp+20h], rsi    ; 홈 영역에 rsi 저장
//   41 54              push r12
//   41 56              push r14
//   41 57              push r15
//   48 83 ec 20        sub rsp, 20h          ; 32바이트 스택 할당
//
// Nuklear 소스에서 nk_draw_list_add_text 파라미터:
//   struct nk_draw_list *list,      -> rcx
//   const struct nk_user_font *font -> rdx
//   struct nk_rect rect,            -> r8, r9 또는 스택 (16바이트)
//   const char *text,               -> 스택
//   int len,                        -> 스택
//   float font_height,              -> 스택/xmm
//   struct nk_color fg              -> 스택 (4바이트)
//
// x64에서 16바이트 구조체(nk_rect)는 포인터로 전달됨
// 따라서: rcx=list, rdx=font, r8=&rect, r9=text, [rsp+28]=len, [rsp+30]=height, [rsp+38]=color

// nk_draw_text 원본 함수 타입 - trampoline 호출용
// 중요: trampoline은 원래 함수의 프롤로그를 포함하므로
// 호출 시 정확히 동일한 레지스터 상태를 전달해야 함
typedef void (*nk_draw_text_fn)(
    uint64_t p1,    // rcx
    uint64_t p2,    // rdx
    uint64_t p3,    // r8 = text
    uint64_t p4,    // r9 = len
    uint64_t p5,    // [rsp+28h] = font
    uint64_t p6,    // [rsp+30h] = bg
    uint64_t p7     // [rsp+38h] = fg
);

static nk_draw_text_fn original_nk_draw_text = NULL;

// trampoline 포인터 (전방 선언 - install_nuklear_hook에서 설정됨)
static void* nk_trampoline = NULL;

// 내부 처리 함수 (C 코드) - naked 래퍼에서 호출됨
// 반환값: 0=원본 호출 필요, 1=이미 처리됨 (변환 완료)
// NOTE: extern 필요 - naked asm에서 call로 참조됨
int nk_draw_text_handler(
    uint64_t p1, uint64_t p2, uint64_t p3, uint64_t p4,
    uint64_t p5, uint64_t p6, uint64_t p7
);

// Naked 어셈블리 래퍼 - 레지스터 상태 완벽 보존
// MinGW에서 __attribute__((naked)) 사용
//
// 스택 레이아웃 (naked 함수 진입 시점):
//   [rsp+0]  = return address (call에 의해 push됨)
//   [rsp+8]  = shadow space (rcx home) - 호출자가 예약
//   [rsp+10] = shadow space (rdx home)
//   [rsp+18] = shadow space (r8 home)
//   [rsp+20] = shadow space (r9 home)
//   [rsp+28] = 5th param (font)
//   [rsp+30] = 6th param (bg)
//   [rsp+38] = 7th param (fg)
//
__attribute__((naked))
static void my_nk_draw_text_naked(void) {
    __asm__ volatile (
        // 중요: 이 함수는 원본 nk_draw_list_add_text를 대체함
        // 원본 파라미터들을 그대로 유지하면서 로깅 후 trampoline 호출
        //
        // Windows x64에서 rcx, rdx, r8, r9는 volatile!
        // 함수 호출 후 값이 보존되지 않으므로 반드시 저장해야 함

        // 모든 파라미터 레지스터 저장
        "push %%rcx\n"
        "push %%rdx\n"
        "push %%r8\n"
        "push %%r9\n"
        "push %%rax\n"
        "push %%r10\n"
        "push %%r11\n"
        "sub $0x28, %%rsp\n"        // shadow space (0x20) + 정렬 (0x8)

        // 스택 오프셋: 7 pushes (0x38) + sub 0x28 = 0x60
        // 원래 [rsp+0x28] (5th param) -> 현재 [rsp + 0x88]

        // 핸들러 호출을 위한 파라미터 설정
        // rcx = 원래 rcx (저장된 위치에서 로드)
        "mov 0x58(%%rsp), %%rcx\n"  // 원래 rcx
        "mov 0x50(%%rsp), %%rdx\n"  // 원래 rdx
        "mov 0x48(%%rsp), %%r8\n"   // 원래 r8
        "mov 0x40(%%rsp), %%r9\n"   // 원래 r9

        // 스택 파라미터 전달 (p5, p6, p7)
        "mov 0x88(%%rsp), %%rax\n"  // 원래 [rsp+0x28] = 5th param
        "mov %%rax, 0x20(%%rsp)\n"
        "mov 0x90(%%rsp), %%rax\n"  // 원래 [rsp+0x30] = 6th param
        "mov %%rax, 0x28(%%rsp)\n"
        "mov 0x98(%%rsp), %%rax\n"  // 원래 [rsp+0x38] = 7th param
        "mov %%rax, 0x30(%%rsp)\n"

        "call nk_draw_text_handler\n"

        // 레지스터 복원
        "add $0x28, %%rsp\n"
        "pop %%r11\n"
        "pop %%r10\n"
        "pop %%rax\n"
        "pop %%r9\n"
        "pop %%r8\n"
        "pop %%rdx\n"
        "pop %%rcx\n"

        // 이제 원본 스택 및 레지스터 상태 완전 복원됨
        // trampoline으로 점프 (원본 함수 실행)
        "jmp *%0\n"
        :
        : "m"(original_nk_draw_text)
        :
    );
}

/**
 * nk_draw_text 핸들러 - C 코드로 텍스트 처리
 * 반환값: 0=원본 호출 필요, 1=이미 처리됨
 *
 * Nuklear 소스 시그니처:
 * void nk_draw_text(struct nk_command_buffer *b, struct nk_rect r,
 *                   const char *text, int len, const struct nk_user_font *font,
 *                   struct nk_color bg, struct nk_color fg)
 *
 * nk_rect = { float x, y, w, h } = 16 bytes
 * nk_color = { nk_byte r,g,b,a } = 4 bytes
 *
 * MSVC x64 호출 규약에서 16바이트 구조체가 값으로 전달될 때:
 * - 호출자가 스택에 복사본을 만들고 포인터를 전달할 수도 있고
 * - 레지스터에 분산되어 전달될 수도 있음 (float이면 XMM 가능)
 *
 * 실제 테스트 결과 파라미터 분석 필요:
 * 여러 파라미터 조합을 시도하여 올바른 text/len 찾기
 */

// nk_draw_text_handler - naked 래퍼에서 호출되는 C 핸들러
// nk_draw_list_add_text 파라미터 분석용 디버그 모드
//
// nk_draw_list_add_text 시그니처 (Nuklear 소스):
//   void nk_draw_list_add_text(
//       struct nk_draw_list *list,      // rcx
//       const struct nk_user_font *font, // rdx
//       struct nk_rect rect,             // ?? (16바이트 구조체)
//       const char *text,                // ??
//       int len,                         // ??
//       float font_height,               // ??
//       struct nk_color fg               // ?? (4바이트)
//   );
//
// 파라미터 위치 분석 필요 - 레지스터와 스택 덤프
int nk_draw_text_handler(
    uint64_t p1,    // rcx - list
    uint64_t p2,    // rdx - font
    uint64_t p3,    // r8
    uint64_t p4,    // r9
    uint64_t p5,    // [rsp+28h]
    uint64_t p6,    // [rsp+30h]
    uint64_t p7     // [rsp+38h]
) {
    InterlockedIncrement(&nk_total_calls);

    // 디버깅 로그 (처음 몇 번만) - 모든 파라미터 덤프
    if (nk_debug_log_count < MAX_NK_DEBUG_LOG) {
        write_log("[NK #%d] rcx=%p rdx=%p r8=%p r9=%p\n",
                  nk_debug_log_count, (void*)p1, (void*)p2, (void*)p3, (void*)p4);
        write_log("[NK #%d] stk: p5=%p p6=%p p7=%p\n",
                  nk_debug_log_count, (void*)p5, (void*)p6, (void*)p7);

        // p3 (r8)이 포인터인지 확인
        if (p3 > 0x10000 && !IsBadReadPtr((void*)p3, 64)) {
            unsigned char* ptr = (unsigned char*)p3;
            write_log("[NK #%d] r8 as ptr: %02x %02x %02x %02x %02x %02x %02x %02x\n",
                      nk_debug_log_count, ptr[0], ptr[1], ptr[2], ptr[3],
                      ptr[4], ptr[5], ptr[6], ptr[7]);
            // 문자열인지 확인
            int is_string = 1;
            for (int i = 0; i < 8; i++) {
                if (ptr[i] != 0 && (ptr[i] < 0x20 || ptr[i] > 0x7E) && ptr[i] < 0x80) {
                    // 제어 문자 (비ASCII 제외) - 문자열 아닐 수 있음
                }
            }
        }

        // p4 (r9)이 포인터인지 확인
        if (p4 > 0x10000 && !IsBadReadPtr((void*)p4, 64)) {
            unsigned char* ptr = (unsigned char*)p4;
            write_log("[NK #%d] r9 as ptr: %02x %02x %02x %02x %02x %02x %02x %02x\n",
                      nk_debug_log_count, ptr[0], ptr[1], ptr[2], ptr[3],
                      ptr[4], ptr[5], ptr[6], ptr[7]);
        }

        // p5가 포인터인지 확인 (스택 파라미터 - text일 가능성)
        if (p5 > 0x10000 && !IsBadReadPtr((void*)p5, 64)) {
            unsigned char* ptr = (unsigned char*)p5;
            write_log("[NK #%d] p5 as ptr: %02x %02x %02x %02x %02x %02x %02x %02x\n",
                      nk_debug_log_count, ptr[0], ptr[1], ptr[2], ptr[3],
                      ptr[4], ptr[5], ptr[6], ptr[7]);
            // 문자열 출력 시도 (ASCII 범위만)
            char preview[32];
            int j = 0;
            for (int i = 0; i < 30 && ptr[i] != 0; i++) {
                if (ptr[i] >= 0x20 && ptr[i] < 0x7F) {
                    preview[j++] = ptr[i];
                } else {
                    preview[j++] = '.';
                }
            }
            preview[j] = 0;
            if (j > 0) {
                write_log("[NK #%d] p5 str: \"%s\"\n", nk_debug_log_count, preview);
            }
        }

        // p6이 len일 가능성 (작은 정수)
        if (p6 > 0 && p6 < 10000) {
            write_log("[NK #%d] p6 as int: %d\n", nk_debug_log_count, (int)p6);
        }

        nk_debug_log_count++;
    }

    // 원본 함수는 naked 래퍼에서 jmp로 호출됨
    // 여기서는 로깅만 담당
    return 1;
}

// 원본 함수 호출은 naked 래퍼(my_nk_draw_text_naked)에서 처리

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

    // out_data 구조체 덤프 (처음 64바이트)
    if (out_data) {
        unsigned char* data_bytes = (unsigned char*)out_data;
        write_log("[Bake] out_data dump (first 64 bytes):\n");
        for (int i = 0; i < 64; i += 16) {
            write_log("[Bake]   +%02x: %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x\n",
                i,
                data_bytes[i+0], data_bytes[i+1], data_bytes[i+2], data_bytes[i+3],
                data_bytes[i+4], data_bytes[i+5], data_bytes[i+6], data_bytes[i+7],
                data_bytes[i+8], data_bytes[i+9], data_bytes[i+10], data_bytes[i+11],
                data_bytes[i+12], data_bytes[i+13], data_bytes[i+14], data_bytes[i+15]);
        }

        // 처음 몇 개 int/float로도 해석
        int* data_ints = (int*)out_data;
        float* data_floats = (float*)out_data;
        write_log("[Bake] out_data as ints: [0]=%d [1]=%d [2]=%d [3]=%d [4]=%d [5]=%d\n",
            data_ints[0], data_ints[1], data_ints[2], data_ints[3], data_ints[4], data_ints[5]);
        write_log("[Bake] out_data as floats: [0]=%.2f [1]=%.2f [2]=%.2f [3]=%.2f\n",
            data_floats[0], data_floats[1], data_floats[2], data_floats[3]);
    }

    // 확장 모드 활성화!
    static int test_mode = 0;  // 1=pass-through, 0=expand
    static int call_count = 0;
    call_count++;

    if (test_mode) {
        // Pass-through 모드: 원본 그대로 호출
        write_log("[Bake #%d] TEST MODE: Pass-through (count=%d)\n", call_count, count);
        write_log("[Bake #%d] Calling original_bake at %p\n", call_count, original_bake);

        // 원본 함수 호출
        write_log("[Bake #%d] Calling with correct signature\n", call_count);

        original_bake(ttf_path, pixel_height, chars_array, count, p5, p6, p7, out_data);

        write_log("[Bake #%d] TEST MODE: Original function called (void return)\n", call_count);
        return;
    }

    // 256자 베이크 요청 감지 및 확장
    if (count == 256 && chars_array != NULL) {
        write_log("[Bake] MATCH! Expanding 256 -> %d chars\n", TOTAL_GLYPH_COUNT);

        init_korean_chars((uint32_t*)chars_array);

        if (korean_chars) {
            // 배열 데이터 검증
            write_log("[Bake] Verify: chars[0]=U+%04X chars[255]=U+%04X chars[256]=U+%04X chars[2605]=U+%04X\n",
                      korean_chars[0], korean_chars[255], korean_chars[256], korean_chars[2605]);

            // 참고: glyph padding은 바이너리 패치로 3->16으로 변경됨 (apply_korean_patch.py)
            // p5 파라미터는 건드리지 않음

            // count를 2606으로 변경하여 호출
            original_bake(ttf_path, pixel_height, korean_chars, TOTAL_GLYPH_COUNT, p5, p6, p7, out_data);
            write_log("[Bake] Expanded bake done (void return)\n");

            // 호출 후 out_data 다시 덤프
            if (out_data) {
                int* data_ints = (int*)out_data;
                write_log("[Bake] AFTER bake - out_data as ints: [0]=%d [1]=%d [2]=%d [3]=%d [4]=%d [5]=%d\n",
                    data_ints[0], data_ints[1], data_ints[2], data_ints[3], data_ints[4], data_ints[5]);

                unsigned char* data_bytes = (unsigned char*)out_data;
                write_log("[Bake] AFTER bake - first 32 bytes:\n");
                for (int i = 0; i < 32; i += 16) {
                    write_log("[Bake]   +%02x: %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x\n",
                        i,
                        data_bytes[i+0], data_bytes[i+1], data_bytes[i+2], data_bytes[i+3],
                        data_bytes[i+4], data_bytes[i+5], data_bytes[i+6], data_bytes[i+7],
                        data_bytes[i+8], data_bytes[i+9], data_bytes[i+10], data_bytes[i+11],
                        data_bytes[i+12], data_bytes[i+13], data_bytes[i+14], data_bytes[i+15]);
                }
            }

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
// Phase 4: Nuklear 한글 지원 - nk_draw_list_add_text 후킹
// ============================================================================
//
// nk_draw_text는 "mov rax, rsp" 프롤로그 때문에 trampoline 불가.
// 대신 nk_draw_list_add_text를 후킹 (단순한 프롤로그).
//
// nk_draw_list_add_text 프롤로그:
//   48 89 5c 24 18     mov [rsp+18h], rbx
//   48 89 74 24 20     mov [rsp+20h], rsi
//   41 54              push r12
//   41 56              push r14
//   41 57              push r15
//   48 83 ec 20        sub rsp, 20h
//
// 이 프롤로그는 "mov rax, rsp" 패턴이 없어 trampoline 호환됨!
//
// Nuklear 소스 시그니처:
//   void nk_draw_list_add_text(
//       struct nk_draw_list *list,      -> rcx
//       const struct nk_user_font *font -> rdx
//       struct nk_rect rect,            -> xmm2/xmm3 또는 스택 (16바이트)
//       const char *text,               -> r9 또는 스택
//       int len,                        -> 스택 [rsp+28h]
//       float font_height,              -> xmm4 또는 스택
//       struct nk_color fg              -> 스택 (4바이트)
//   );
//
// 실제 파라미터 분석 필요 - 첫 호출에서 로그 덤프

static volatile int nk_hook_active = 0;

// 원본 함수 백업
static uint8_t nk_original_bytes[20];  // 프롤로그 20바이트

// RVA: 0xa824b0
#define NK_DRAW_LIST_ADD_TEXT_RVA  0xa824b0

// 예상 프롤로그 (검증용) - 20바이트
static const uint8_t NK_EXPECTED_PROLOGUE[] = {
    0x48, 0x89, 0x5c, 0x24, 0x18,  // mov [rsp+18h], rbx  (5)
    0x48, 0x89, 0x74, 0x24, 0x20,  // mov [rsp+20h], rsi  (5)
    0x41, 0x54,                    // push r12            (2)
    0x41, 0x56,                    // push r14            (2)
    0x41, 0x57,                    // push r15            (2)
    0x48, 0x83, 0xec, 0x20         // sub rsp, 20h        (4) = 20바이트 총합
};

/**
 * nk_draw_list_add_text 함수 위치 확인
 *
 * 바이너리 분석 결과:
 * - RVA: 0xa824b0
 * - 단순한 프롤로그 (mov rax, rsp 없음) - trampoline 호환!
 */
static void* find_nk_draw_list_add_text_function(void) {
    void* addr = (void*)((uintptr_t)nwmain_base + NK_DRAW_LIST_ADD_TEXT_RVA);
    uint8_t* bytes = (uint8_t*)addr;

    write_log("[Phase 4] Checking nk_draw_list_add_text at RVA 0x%x\n", NK_DRAW_LIST_ADD_TEXT_RVA);
    write_log("[Phase 4] Prologue: %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x\n",
              bytes[0], bytes[1], bytes[2], bytes[3], bytes[4], bytes[5],
              bytes[6], bytes[7], bytes[8], bytes[9], bytes[10], bytes[11],
              bytes[12], bytes[13], bytes[14], bytes[15], bytes[16], bytes[17],
              bytes[18], bytes[19]);

    // 프롤로그 검증
    if (memcmp(bytes, NK_EXPECTED_PROLOGUE, sizeof(NK_EXPECTED_PROLOGUE)) == 0) {
        write_log("[Phase 4] Prologue verified - function found!\n");
        return addr;
    }

    write_log("[Phase 4] WARNING: Prologue mismatch - binary version may differ\n");
    write_log("[Phase 4] Expected: 48 89 5c 24 18 48 89 74 24 20 41 54 41 56 41 57 48 83 ec 20\n");

    // 첫 5바이트 (mov [rsp+18h], rbx)가 일치하면 시도
    if (bytes[0] == 0x48 && bytes[1] == 0x89 && bytes[2] == 0x5c &&
        bytes[3] == 0x24 && bytes[4] == 0x18) {
        write_log("[Phase 4] Partial match - proceeding with caution\n");
        return addr;
    }

    return NULL;
}

/**
 * Nuklear nk_draw_list_add_text 함수 인라인 후킹
 *
 * nk_draw_text는 "mov rax, rsp" 프롤로그 때문에 trampoline 불가.
 * nk_draw_list_add_text는 단순한 프롤로그를 가지므로 trampoline 호환!
 *
 * 프롤로그 (20바이트):
 *   +00: 48 89 5c 24 18     mov [rsp+18h], rbx  (5)
 *   +05: 48 89 74 24 20     mov [rsp+20h], rsi  (5)
 *   +10: 41 54              push r12            (2)
 *   +12: 41 56              push r14            (2)
 *   +14: 41 57              push r15            (2)
 *   +16: 48 83 ec 20        sub rsp, 20h        (4) = 20바이트 총합
 */
static BOOL install_nuklear_hook(void) {
    if (nk_hook_active) return TRUE;

    // 함수 위치 검색
    void* func_addr = find_nk_draw_list_add_text_function();

    if (!func_addr) {
        write_log("[Phase 4] Could not find nk_draw_list_add_text function\n");
        write_log("[Phase 4] Nuklear Korean support will be limited\n");
        return FALSE;
    }

    write_log("[Phase 4] nk_draw_list_add_text at: %p\n", func_addr);

    // 프롤로그 크기 = 20바이트 (명령어 경계에서 정확히 끊김)
    #define HOOK_SIZE 20

    // 원본 바이트 백업
    memcpy(nk_original_bytes, func_addr, HOOK_SIZE);

    // 트램폴린 생성 - 원본 프롤로그 실행 후 원래 함수+20으로 점프
    nk_trampoline = VirtualAlloc(NULL, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!nk_trampoline) {
        write_log("[Phase 4] ERROR: VirtualAlloc failed for trampoline\n");
        return FALSE;
    }

    uint8_t* tramp = (uint8_t*)nk_trampoline;
    memcpy(tramp, func_addr, HOOK_SIZE);

    // jmp [rip+0] 형식 (FF 25 00 00 00 00 + 8바이트 주소)
    tramp[HOOK_SIZE + 0] = 0xFF;
    tramp[HOOK_SIZE + 1] = 0x25;
    tramp[HOOK_SIZE + 2] = 0x00;
    tramp[HOOK_SIZE + 3] = 0x00;
    tramp[HOOK_SIZE + 4] = 0x00;
    tramp[HOOK_SIZE + 5] = 0x00;
    *(uint64_t*)(tramp + HOOK_SIZE + 6) = (uint64_t)func_addr + HOOK_SIZE;

    original_nk_draw_text = (nk_draw_text_fn)nk_trampoline;

    write_log("[Phase 4] Trampoline at: %p\n", nk_trampoline);
    write_log("[Phase 4] Trampoline bytes: %02x %02x %02x %02x %02x %02x %02x %02x\n",
              tramp[0], tramp[1], tramp[2], tramp[3], tramp[4], tramp[5], tramp[6], tramp[7]);

    // 원본 함수 시작 부분을 jmp hook으로 교체
    DWORD old_protect;
    if (!VirtualProtect(func_addr, HOOK_SIZE, PAGE_EXECUTE_READWRITE, &old_protect)) {
        write_log("[Phase 4] ERROR: VirtualProtect failed (error %d)\n", GetLastError());
        VirtualFree(nk_trampoline, 0, MEM_RELEASE);
        nk_trampoline = NULL;
        return FALSE;
    }

    // jmp [rip+0] 형식 (14바이트)
    uint8_t* hook = (uint8_t*)func_addr;
    hook[0] = 0xFF;
    hook[1] = 0x25;
    hook[2] = 0x00;
    hook[3] = 0x00;
    hook[4] = 0x00;
    hook[5] = 0x00;
    *(uint64_t*)(hook + 6) = (uint64_t)my_nk_draw_text_naked;

    // 나머지 6바이트는 NOP으로 채움 (HOOK_SIZE=20, jmp=14바이트)
    for (int i = 14; i < HOOK_SIZE; i++) {
        hook[i] = 0x90;  // NOP
    }

    VirtualProtect(func_addr, HOOK_SIZE, old_protect, &old_protect);

    nk_hook_active = 1;
    write_log("[Phase 4] Nuklear nk_draw_list_add_text hook installed!\n");
    write_log("[Phase 4] Original: %p -> Hook: %p -> Trampoline: %p\n",
              func_addr, my_nk_draw_text_naked, nk_trampoline);

    return TRUE;

    #undef HOOK_SIZE
}

/**
 * Phase 4 지연 훅킹 스레드
 *
 * Nuklear UI가 초기화된 후 nk_user_font 구조체를 찾아 후킹
 */
static DWORD WINAPI nuklear_hook_thread(LPVOID param) {
    (void)param;

    write_log("[Phase 4 Thread] Started - waiting for Nuklear initialization...\n");

    // Nuklear는 게임 시작 후 몇 초 뒤에 초기화됨
    Sleep(5000);  // 5초 대기

    for (int attempts = 0; attempts < 60; attempts++) {
        if (nk_hook_active) {
            write_log("[Phase 4 Thread] Hook already active, exiting\n");
            return 0;
        }

        if (install_nuklear_hook()) {
            write_log("[Phase 4 Thread] SUCCESS! Nuklear hook installed\n");
            return 0;
        }

        Sleep(1000);  // 1초 간격

        if (attempts % 10 == 0 && attempts > 0) {
            write_log("[Phase 4 Thread] Still searching... attempt %d\n", attempts);
        }
    }

    write_log("[Phase 4 Thread] TIMEOUT - could not hook nk_draw_list_add_text\n");
    write_log("[Phase 4 Thread] Nuklear UI Korean text may not display correctly\n");
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
            fprintf(log, "NWN:EE Korean Hook DLL (Windows x64) - Phase 2+4\n");
            fprintf(log, "=================================================\n\n");
            fclose(log);
        }

        write_log("[NWN Korean Hook] Initializing (Phase 2: Bake + Phase 4: Nuklear)...\n");

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
        // 참고: advance 값이 0.1~0.9 범위의 정규화된 값이라 단순 배수 조정으로는 해결 안됨
        // macOS 구현에서는 CalculateVisibleStringLengthAndWidth 함수를 패치하여 해결
        // Windows에서도 동일한 접근이 필요할 수 있음
        write_log("[Hook] GetSymbolCoords hook DISABLED (advance value is normalized, need different approach)\n");

        // Phase 4: Nuklear 한글 지원 - 비활성화
        // 트램폴린 방식이 mov [rsp+xx], reg 프롤로그와 호환되지 않아 크래시 발생
        // 대신 바이너리 패치 방식으로 해결 예정 (apply_korean_patch.py에서 처리)
        write_log("[Phase 4] Nuklear hook DISABLED (trampoline incompatible with prologue)\n");
        write_log("[Phase 4] Use binary patch for Nuklear Korean support\n");
        // CreateThread(NULL, 0, nuklear_hook_thread, NULL, 0, NULL);

        write_log("\n=== Korean Hook Ready ===\n");
        write_log("Glyph range: 0-255 (base) + 256-2605 (Korean)\n");
        write_log("Mode: Bake hook (Phase 2) only\n");
        write_log("Input encoding: CP949\n");
        write_log("Note: Nuklear UI requires binary patch for Korean support\n");
        write_log("\n");
    }
    else if (fdwReason == DLL_PROCESS_DETACH) {
        // 통계 로그
        write_log("\n=== Final Statistics ===\n");
        write_log("[NK Stats] Total calls: %ld, Conversions: %ld\n",
                  nk_total_calls, nk_conversion_count);

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
