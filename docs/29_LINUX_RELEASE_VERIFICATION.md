# Linux portable v0.2.1 r1 검수 기록

검수일: 2026-07-23

브랜치: `codex/linux-portable`

## 1. 검수 대상

- Windows/Linux 공용 packaged GUI 진입점
- Linux XDG config/data/state 경로
- Ubuntu 22.04 x86_64 PyInstaller one-file build
- offscreen 통합 시작 화면 smoke
- tar.gz 실행 권한 보존과 SHA-256
- GitHub Actions artifact

## 2. Windows 개발 PC 사전 검수

- XDG/Windows runtime path 단위 테스트: 통과
- packaged dataset argument 단위 테스트: 통과
- workflow dialog 회귀 테스트: 통과
- 전체 pytest: `120 passed`
- 전체 `ruff check .`: 통과
- 공용 packaged 시작 화면 offscreen smoke: 통과, 자동 종료 code 0
- Linux build/package shell `bash -n`: 통과
- `git diff --check`: 통과

현재 개발 PC에는 WSL 배포판과 Docker가 없다. PyInstaller는 교차 컴파일을 지원하지 않으므로
Windows에서 Linux ELF를 만들었다고 주장하지 않는다.

## 3. Linux 네이티브 Gate

아래 항목은 첫 GitHub Actions 실행 결과로 갱신한다.

- [ ] Ubuntu 22.04 전체 pytest
- [ ] Ubuntu 22.04 ruff
- [ ] one-file PyInstaller build
- [ ] offscreen `LiDARLabelTool --smoke-test`
- [ ] Xvfb/xcb `LiDARLabelTool --smoke-test`
- [ ] release tar.gz SHA-256 check
- [ ] artifact 업로드와 다운로드 가능 여부

## 4. clean Linux Gate

GitHub runner의 headless smoke는 실제 현장 GUI 검수를 대신하지 않는다.

- [ ] Python 미설치 Ubuntu 22.04 x86_64
- [ ] 한글·공백 경로
- [ ] one_chip 실제 MCAP/YAML 전체 변환
- [ ] `one_chip_converted` Preflight
- [ ] LiDAR와 CAM_LEFT/CAM_RIGHT frame 진행
- [ ] calibration projection overlay
- [ ] box 저장·재로드
- [ ] X11/Wayland-XWayland와 OpenGL 드라이버
- [ ] 취소·실패 후 원본/기존 output 보존

## 5. 현재 결론

Linux 소스 호환성과 네이티브 CI 배포 경로는 구현했다. 배포 후보 승인은 GitHub Actions의 실제
Linux 빌드가 통과한 뒤 가능하며, 최종 운영 승인은 별도 clean Linux PC에서 one_chip 데이터와
projection을 확인한 뒤 내린다.
