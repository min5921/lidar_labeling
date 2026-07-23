# Windows/Linux 영구 GitHub Release

## 1. 목적

GitHub Actions의 임시 artifact 대신 GitHub Release에 Windows와 Linux 사용자 배포 파일을
함께 올린다. Release 자산은 태그와 함께 명시적으로 삭제하지 않는 한 만료되지 않는다.

공식 다운로드:

```text
https://github.com/min5921/lidar_labeling/releases/latest
```

v0.2.1 고정 주소:

```text
https://github.com/min5921/lidar_labeling/releases/tag/v0.2.1
```

## 2. v0.2.1 자산

```text
LiDARLabelTool_Integrated_0.2.1_windows_x86_64.exe
LiDARLabelTool_Integrated_0.2.1_windows_x86_64.sha256.txt
LiDARLabelTool_Integrated_0.2.1_linux_x86_64.tar.gz
LiDARLabelTool_Integrated_0.2.1_linux_x86_64.tar.gz.sha256.txt
```

Windows EXE는 Windows Server 2022 runner, Linux tar.gz는 Ubuntu 22.04 runner에서 각각
네이티브 빌드한다. 서로 다른 운영체제 산출물을 한 runner에서 교차 컴파일하지 않는다.

## 3. 자동 배포

`.github/workflows/publish-desktop-release.yml`은 `codex/linux-portable`의 배포 관련 변경 push에서
Windows/Linux 빌드를 사전 검증하고, `vX.Y.Z` 형식의 태그 push에서는 검증 후 Release까지 만든다.

1. 태그와 `pyproject.toml` 버전 일치 여부 확인
2. Windows 전체 테스트, Ruff, one-file 빌드, packaged smoke
3. Ubuntu 전체 테스트, Ruff, one-file 빌드, offscreen/xcb smoke
4. 운영체제별 패키지와 SHA-256 생성
5. 태그 실행에서 두 빌드가 모두 성공한 경우에만 GitHub Release 생성
6. 네 개의 자산을 Release에 영구 첨부

릴리스 생성 예:

```powershell
git tag -a v0.2.1 -m "LiDAR Label Tool v0.2.1"
git push origin v0.2.1
```

같은 태그를 다시 사용하지 않는다. 수정 배포는 프로젝트 버전과 메타데이터를 올리고 새 태그를
사용한다.

기존 `.github/workflows/build-linux-portable.yml`은 이전 Linux artifact 재현이 필요할 때 수동으로
실행한다. 일반 branch 검증과 영구 배포는 통합 release workflow가 담당한다.

## 4. 사용자 검증

Windows:

```powershell
Get-FileHash -Algorithm SHA256 `
  .\LiDARLabelTool_Integrated_0.2.1_windows_x86_64.exe
Get-Content `
  .\LiDARLabelTool_Integrated_0.2.1_windows_x86_64.sha256.txt
```

Linux:

```bash
sha256sum --check \
  LiDARLabelTool_Integrated_0.2.1_linux_x86_64.tar.gz.sha256.txt
tar -xzf LiDARLabelTool_Integrated_0.2.1_linux_x86_64.tar.gz
cd LiDARLabelTool_Integrated_0.2.1_linux_x86_64
./LiDARLabelTool
```

## 5. 운영 Gate와 제한

- Release 자산은 영구 보관되지만 별도 백업도 유지한다.
- Windows EXE는 아직 코드 서명이 없어 SmartScreen 경고가 나올 수 있다.
- Linux는 Ubuntu 22.04 이상 x86_64, X11/XWayland, OpenGL 드라이버를 기준으로 한다.
- 깨끗한 실제 PC에서 한글·공백 경로와 one_chip 전체 workflow를 최종 확인한다.
- 프로젝트 자체 오픈소스 라이선스는 아직 선언되지 않았다. 공개 사용·재배포 정책은 저장소
  소유자가 별도로 확정한다.
- `THIRD_PARTY_NOTICES.md`와 번들에 포함된 제3자 라이선스 파일을 제거하지 않는다.
