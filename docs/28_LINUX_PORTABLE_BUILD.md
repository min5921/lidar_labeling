# Linux 포터블 빌드와 배포 매뉴얼

## 1. 배포 목표

Ubuntu 22.04 이상 x86_64 데스크톱에서 Python, pip, ROS2 없이 통합 GUI를 실행한다. Linux에는
`.exe` 확장자가 없으며 배포본의 `LiDARLabelTool`은 Windows EXE에 대응하는 단일 ELF 실행
파일이다.

지원 기준:

- Ubuntu 22.04 LTS x86_64
- Python 3.12로 빌드
- PySide6 6.11.1
- PyInstaller 6.21.0 one-file
- X11 또는 XWayland를 제공하는 데스크톱과 OpenGL 드라이버

ARM64, 32-bit Linux, Ubuntu 20.04 이하, macOS는 이 산출물의 지원 범위가 아니다.

## 2. 사용자 실행

GitHub Actions artifact ZIP을 풀면 다음 두 파일이 나온다.

```text
LiDARLabelTool_Integrated_0.2.1_linux_x86_64_r1.tar.gz
LiDARLabelTool_Integrated_0.2.1_linux_x86_64_r1.tar.gz.sha256.txt
```

현재 검수본 다운로드는 `docs/29_LINUX_RELEASE_VERIFICATION.md`의 run/artifact 링크를 사용한다.
Actions artifact는 30일 후 만료되므로 운영 승인본은 프로젝트 라이선스 확정 후 GitHub Release
또는 사내 배포 저장소에 별도로 보관한다.

무결성을 확인하고 실행한다.

```bash
sha256sum --check \
  LiDARLabelTool_Integrated_0.2.1_linux_x86_64_r1.tar.gz.sha256.txt
tar -xzf LiDARLabelTool_Integrated_0.2.1_linux_x86_64_r1.tar.gz
cd LiDARLabelTool_Integrated_0.2.1_linux_x86_64_r1
./LiDARLabelTool
```

압축을 푼 실행 파일은 이미 executable mode를 가진다. 이메일·메신저 등 실행 권한을 지우는 전달
경로를 거쳤다면 `chmod +x LiDARLabelTool`을 한 번 실행한다.

## 3. 사용자 경로

Linux 표준 XDG 경로를 사용한다.

```text
설정: ${XDG_CONFIG_HOME:-$HOME/.config}/LiDARLabelTool/settings.ini
로그: ${XDG_STATE_HOME:-$HOME/.local/state}/LiDARLabelTool/logs/
데이터: ${XDG_DATA_HOME:-$HOME/.local/share}/LiDARLabelTool/
```

원본 MCAP/YAML, 변환 dataset, 작업 라벨, export 결과는 실행 파일 밖에서 사용자가 선택한다.

## 4. Linux 개발 PC에서 직접 빌드

```bash
git switch codex/linux-portable
bash packaging/build_linux_portable.sh --python python3 --onefile
bash packaging/package_linux_release.sh \
  LiDARLabelTool_Integrated_0.2.1_linux_x86_64_r1
```

빌드 스크립트는 다음 순서로 동작한다.

1. `.build/linux-portable-venv` 생성
2. `linux_build_constraints.txt`를 적용해 의존성 설치
3. `pytest`, `ruff check .` 실행
4. PyInstaller one-file 생성
5. `--smoke-test`로 통합 시작 화면을 offscreen 실행
6. 정확한 `pip freeze`를 `build/linux-build-dependencies.txt`에 기록
7. 실행 권한을 보존하는 tar.gz와 SHA-256 생성

`--skip-tests`, `--skip-dependency-install`, `--skip-smoke`는 각 단계를 별도로 이미 검증한 반복
빌드에서만 사용한다.

## 5. GitHub Actions 빌드

`.github/workflows/build-linux-portable.yml`은 `codex/linux-portable`의 코드·패키징 변경 push와
수동 실행에서 동작한다. Ubuntu 22.04 runner가 테스트, 빌드, smoke, hash 검증을 모두 통과해야
artifact를 업로드한다. 보관 기간은 30일이다.

PyInstaller는 교차 컴파일러가 아니므로 Windows PC에서 생성한 파일을 Linux 배포본으로 사용하지
않는다. 이 저장소의 Windows PC에는 WSL/Docker가 없으므로 네이티브 Linux 산출물 확인은 GitHub
Actions 결과를 기준으로 한다.

## 6. Linux 시스템 라이브러리

PyInstaller는 Python과 Python package를 묶지만 glibc와 기본 운영체제 라이브러리를 모두 포함하지
않는다. Qt xcb 또는 OpenGL loader 오류가 발생하면 Ubuntu에서 다음을 설치한다.

```bash
sudo apt update
sudo apt install \
  libdbus-1-3 libegl1 libfontconfig1 libgl1 libglib2.0-0 libice6 libopengl0 \
  libsm6 libx11-6 libx11-xcb1 libxcb1 libxcb-cursor0 libxcb-glx0 \
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
  libxcb-render-util0 libxcb-shape0 libxcb-shm0 libxcb-sync1 libxcb-util1 \
  libxcb-xfixes0 libxcb-xinerama0 libxcb-xkb1 libxext6 libxi6 \
  libxkbcommon-x11-0 libxrender1
```

지원 범위를 Ubuntu 22.04 이상으로 고정한 이유는 Qt/PySide6 wheel과 glibc 호환성을 예측 가능하게
만들기 위해서다.

## 7. clean Linux 검수

1. Python과 개발 도구가 없는 Ubuntu 22.04 x86_64 PC/VM을 준비한다.
2. 한글과 공백이 있는 경로에 tar.gz를 풀고 실행한다.
3. 통합 시작 화면에서 one_chip 전체 변환과 재동기화를 실행한다.
4. Preflight 후 dataset을 열어 LiDAR, 양쪽 camera, projection을 확인한다.
5. 박스를 생성·수정·저장하고 앱 재시작 후 ID/class/box 값 유지 여부를 확인한다.
6. calibration ON/OFF, 실제 사용 행렬, overlay를 확인한다.
7. 취소·실패 시 staging과 기존 `frames.jsonl` 보존 여부를 확인한다.
8. XDG 설정·crash log가 실행 파일 옆이 아닌 사용자 경로에 생성되는지 확인한다.
9. X11과 Wayland/XWayland 세션에서 각각 실행하고 그래픽 드라이버/원격 세션 결과를 기록한다.

## 8. 알려진 제한

- 배포 파일은 Ubuntu 계열 x86_64용이며 모든 Linux 배포판을 보장하지 않는다.
- one-file은 첫 실행 때 임시 폴더에 내부 파일을 풀어 시작이 느릴 수 있다.
- OpenGL 드라이버와 Qt의 일부 xcb 시스템 라이브러리는 운영체제가 제공해야 한다.
- 현재 프로젝트 자체 라이선스가 선언되지 않아 공개 재배포 전 결정이 필요하다.
- Linux 코드 서명과 자동 업데이트는 아직 제공하지 않는다.
