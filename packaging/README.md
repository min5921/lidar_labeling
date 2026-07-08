# Packaging

이 폴더에는 재현 가능한 Windows 배포 자료를 둔다.

- `build_windows_portable.ps1`: 테스트 후 PyInstaller one-folder 빌드
- `windows_entry.py`: 폴더 선택 창으로 시작하는 GUI 전용 진입점
- installer 설정(채택 시)
- version metadata
- third-party license 목록 생성 설정

빌드 결과물은 이 폴더에 넣지 않고 Git에서 제외된 `dist/`에 생성한다. 자세한 절차는
`docs/17_WINDOWS_PORTABLE_BUILD.md`를 따른다. 스크립트는 사용자별 절대 경로를 포함하지 않는다.
