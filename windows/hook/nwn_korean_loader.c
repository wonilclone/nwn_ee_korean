/*
 * NWN Korean Patch Loader
 *
 * 게임 시작 시 nwn_korean_hook.dll을 자동으로 인젝션합니다.
 */

#include <windows.h>
#include <stdio.h>
#include <stdlib.h>

#define LOG_FILE "nwn_korean_loader.log"

// 로그 함수
static void log_message(const char* msg) {
    FILE* log = fopen(LOG_FILE, "a");
    if (log) {
        SYSTEMTIME st;
        GetLocalTime(&st);
        fprintf(log, "[%02d:%02d:%02d] %s\n", st.wHour, st.wMinute, st.wSecond, msg);
        fclose(log);
    }
}

// DLL 인젝션 함수
BOOL inject_dll(HANDLE hProcess, const char* dll_path) {
    LPVOID remote_string;
    HANDLE remote_thread;
    SIZE_T bytes_written;

    log_message("Starting DLL injection...");

    // DLL 경로 길이
    size_t dll_path_len = strlen(dll_path) + 1;

    // 원격 프로세스에 메모리 할당
    remote_string = VirtualAllocEx(hProcess, NULL, dll_path_len,
                                   MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);

    if (!remote_string) {
        log_message("ERROR: VirtualAllocEx failed");
        return FALSE;
    }

    // DLL 경로를 원격 프로세스에 쓰기
    if (!WriteProcessMemory(hProcess, remote_string, dll_path, dll_path_len, &bytes_written)) {
        log_message("ERROR: WriteProcessMemory failed");
        VirtualFreeEx(hProcess, remote_string, 0, MEM_RELEASE);
        return FALSE;
    }

    // LoadLibraryA 주소 가져오기
    LPVOID load_library_addr = (LPVOID)GetProcAddress(GetModuleHandleA("kernel32.dll"), "LoadLibraryA");
    if (!load_library_addr) {
        log_message("ERROR: GetProcAddress failed");
        VirtualFreeEx(hProcess, remote_string, 0, MEM_RELEASE);
        return FALSE;
    }

    // 원격 스레드 생성하여 LoadLibraryA 호출
    remote_thread = CreateRemoteThread(hProcess, NULL, 0,
                                      (LPTHREAD_START_ROUTINE)load_library_addr,
                                      remote_string, 0, NULL);

    if (!remote_thread) {
        log_message("ERROR: CreateRemoteThread failed");
        VirtualFreeEx(hProcess, remote_string, 0, MEM_RELEASE);
        return FALSE;
    }

    // 스레드 완료 대기
    WaitForSingleObject(remote_thread, INFINITE);

    // 정리
    CloseHandle(remote_thread);
    VirtualFreeEx(hProcess, remote_string, 0, MEM_RELEASE);

    log_message("DLL injection successful");
    return TRUE;
}

int main(int argc, char* argv[]) {
    STARTUPINFOA si = {0};
    PROCESS_INFORMATION pi = {0};
    char game_path[MAX_PATH];
    char dll_path[MAX_PATH];
    char cmd_line[2048] = {0};
    char log_msg[512];

    // 로그 초기화
    FILE* log = fopen(LOG_FILE, "w");
    if (log) {
        fprintf(log, "===========================================\n");
        fprintf(log, "NWN Korean Patch Loader\n");
        fprintf(log, "===========================================\n\n");
        fclose(log);
    }

    log_message("Loader started");

    // 현재 디렉토리에서 nwmain.exe 경로 구성
    GetCurrentDirectoryA(MAX_PATH, game_path);
    strcat(game_path, "\\nwmain.exe");

    // DLL 경로 구성 (절대 경로)
    GetCurrentDirectoryA(MAX_PATH, dll_path);
    strcat(dll_path, "\\nwn_korean_hook.dll");

    sprintf(log_msg, "Game path: %s", game_path);
    log_message(log_msg);
    sprintf(log_msg, "DLL path: %s", dll_path);
    log_message(log_msg);

    // DLL 파일 존재 확인
    if (GetFileAttributesA(dll_path) == INVALID_FILE_ATTRIBUTES) {
        log_message("ERROR: nwn_korean_hook.dll not found!");
        MessageBoxA(NULL, "nwn_korean_hook.dll not found!", "Error", MB_OK | MB_ICONERROR);
        return 1;
    }

    // 게임 실행 파일 존재 확인
    if (GetFileAttributesA(game_path) == INVALID_FILE_ATTRIBUTES) {
        log_message("ERROR: nwmain.exe not found!");
        MessageBoxA(NULL, "nwmain.exe not found!", "Error", MB_OK | MB_ICONERROR);
        return 1;
    }

    // 명령줄 인자 복사 (첫 번째 인자는 프로그램 이름이므로 건너뜀)
    for (int i = 1; i < argc; i++) {
        if (i > 1) strcat(cmd_line, " ");
        strcat(cmd_line, argv[i]);
    }

    if (cmd_line[0]) {
        sprintf(log_msg, "Command line: %s", cmd_line);
        log_message(log_msg);
    }

    // 게임 디렉토리 추출 (작업 디렉토리로 사용)
    char game_dir[MAX_PATH];
    GetCurrentDirectoryA(MAX_PATH, game_dir);

    sprintf(log_msg, "Working directory: %s", game_dir);
    log_message(log_msg);

    // 게임 프로세스를 일시 중단 상태로 생성
    si.cb = sizeof(si);

    log_message("Creating game process (suspended)...");

    if (!CreateProcessA(game_path, cmd_line[0] ? cmd_line : NULL, NULL, NULL, FALSE,
                       CREATE_SUSPENDED, NULL, game_dir, &si, &pi)) {
        log_message("ERROR: Failed to create game process");
        sprintf(log_msg, "Error code: %lu", GetLastError());
        log_message(log_msg);
        MessageBoxA(NULL, "Failed to start game!", "Error", MB_OK | MB_ICONERROR);
        return 1;
    }

    log_message("Game process created (suspended)");
    sprintf(log_msg, "Process ID: %lu", pi.dwProcessId);
    log_message(log_msg);

    // DLL 인젝션
    if (!inject_dll(pi.hProcess, dll_path)) {
        log_message("ERROR: DLL injection failed");
        TerminateProcess(pi.hProcess, 1);
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
        MessageBoxA(NULL, "Failed to inject Korean patch DLL!", "Error", MB_OK | MB_ICONERROR);
        return 1;
    }

    // 프로세스 재개
    log_message("Resuming game process...");
    ResumeThread(pi.hThread);

    // 핸들 정리
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);

    log_message("Game launched successfully with Korean patch");

    return 0;
}
