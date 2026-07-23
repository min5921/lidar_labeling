# Packaging

이 폴더에는 재현 가능한 Windows와 Linux 배포 자료를 둔다.

- `build_windows_portable.ps1`: 테스트 후 PyInstaller one-folder 빌드
- `build_windows_portable.ps1 -OneFile`: 통합 사용자 기능을 포함한 단일 EXE 빌드
- `windows_build_constraints.txt`: Windows 릴리스의 핵심 GUI/패키저 버전 고정
- `package_windows_onefile_release.ps1`: 단일 EXE 이름 고정, 복사, SHA-256 생성
- `package_windows_release.ps1`: 배포 폴더, 실행 배치, 매뉴얼, ZIP, SHA-256 생성
- `portable_bundle/`: 최종 배포 폴더에 복사되는 launcher/readme 원본
- `windows_entry.py`: 폴더 선택 창으로 시작하는 GUI 전용 진입점
- `build_linux_portable.sh`: Linux x86_64 테스트, one-folder/one-file 빌드, headless smoke
- `package_linux_release.sh`: Linux 실행 파일, 매뉴얼, 의존성 기록, tar.gz, SHA-256 생성
- `linux_build_constraints.txt`: Linux 릴리스의 핵심 GUI/패키저 버전 고정
- `linux_bundle/`: Linux 최종 배포본에 포함되는 사용자 매뉴얼
- `linux_entry.py`: Linux GUI 진입점
- `.github/workflows/build-linux-portable.yml`: Ubuntu 22.04 네이티브 빌드와 artifact 업로드
- `.github/workflows/publish-desktop-release.yml`: 태그 기반 Windows/Linux 영구 GitHub Release
- installer 설정(채택 시)
- version metadata
- third-party license 목록 생성 설정

빌드 결과물은 이 폴더에 넣지 않고 Git에서 제외된 `dist/`에 생성한다. 자세한 절차는
Windows는 `docs/17_WINDOWS_PORTABLE_BUILD.md`, Linux는 `docs/28_LINUX_PORTABLE_BUILD.md`를
따른다. 스크립트는 사용자별 절대 경로를 포함하지 않는다.
