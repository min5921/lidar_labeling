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
- 전체 pytest: `121 passed`
- 전체 `ruff check .`: 통과
- 공용 packaged 시작 화면 offscreen smoke: 통과, 자동 종료 code 0
- Linux build/package shell `bash -n`: 통과
- `git diff --check`: 통과

현재 개발 PC에는 WSL 배포판과 Docker가 없다. PyInstaller는 교차 컴파일을 지원하지 않으므로
Windows에서 Linux ELF를 만들었다고 주장하지 않는다.

## 3. Linux 네이티브 Gate

최종 GitHub Actions run:

```text
run: 29985332303
commit: dc15cc4087cbf639eeb4b017284312df0a88de29
runner: Ubuntu 22.04.5 x86_64
Python: 3.12.13
PyInstaller: 6.21.0
PySide6: 6.11.1
```

- [x] Ubuntu 22.04 pytest: `114 passed, 7 skipped`
- [x] Ubuntu 22.04 `ruff check .`
- [x] one-file PyInstaller build
- [x] offscreen `LiDARLabelTool --smoke-test`
- [x] Xvfb/xcb `LiDARLabelTool --smoke-test`
- [x] release tar.gz SHA-256 check
- [x] artifact 업로드와 다운로드 가능 여부

Linux CI의 7개 skip은 runner에 Git 제외 로컬 Waymo sample이 없어서 생긴 integration skip이다. 단위
테스트 실패가 아니다.

## 4. 배포 후보

GitHub Actions artifact:

```text
name: LiDARLabelTool_Integrated_0.2.1_linux_x86_64_r1
artifact id: 8554809220
artifact size: 115376432 bytes
artifact SHA-256: 453ab54e953c3211e09d598c7736e77cfc55efbbf948e0a21993969447058a5f
tar.gz SHA-256: 56f2a6d2a9b49b73ea7f4ff8b58b528d0ec7f80585cc1f3a9d53aab8ae6fe45d
expires: 2026-08-22 06:34 UTC
```

다운로드:

```text
https://github.com/min5921/lidar_labeling/actions/runs/29985332303/artifacts/8554809220
```

artifact ZIP 안에는 tar.gz와 tar.gz SHA-256 파일이 있다. tar.gz 안에는 실행 파일
`LiDARLabelTool`, `README_FIRST.md`, `THIRD_PARTY_NOTICES.md`,
`BUILD_DEPENDENCIES.txt`가 있고 archive 목록 검사가 통과했다.

## 5. clean Linux Gate

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

## 6. CI 수정 이력

- 첫 run: 일반 wheel 설치에서 기본 config를 찾지 못한 문제를 설치 data-file 계약으로 수정
- 두 번째 run: 사용하지 않는 `pyqtgraph.examples` 수집 중 display 오류를 필요한 module만 수집하도록 수정
- 세 번째 run: hash 파일 기준 경로를 `release_packages`로 맞춤
- 최종 run: Node 24 기반 checkout/setup/upload action으로 전 단계 통과

## 7. 현재 결론

Linux 소스 호환성과 네이티브 CI 배포 경로를 구현했고 v0.2.1 r1을 CI 배포 후보로 승인한다.
최종 운영 승인은 별도 clean Linux PC에서 one_chip 실제 변환, frame 진행, calibration projection,
저장·재로드를 확인한 뒤 내린다. 프로젝트 라이선스가 미정이므로 현재 후보는 30일 artifact로
보관하고 영구 공개 GitHub Release는 만들지 않았다.

> 후속 상태: 이 임시 후보는 Windows/Linux 통합 `v0.2.2` GitHub Release로 영구 배포되었다.
> 최종 링크와 SHA-256은 `docs/30_GITHUB_RELEASE.md`를 따른다.
