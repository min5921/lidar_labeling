# 실행 파일

사용자용 설치·실행 파일은 이 폴더에서 관리한다. 모든 스크립트는 자신의 위치를 기준으로
저장소 루트를 찾으므로, 탐색기에서 더블클릭하거나 저장소 루트에서 실행할 수 있다.

## Windows

- 최초 설치 또는 의존성 갱신: `windows/setup_windows.bat`
- 라벨링 도구 실행: `windows/run_windows.bat`

새 PC에서 `QtWidgets` DLL 오류가 발생하면 저장소 루트의 PowerShell에서 다음 순서로 복구한다.

```powershell
.\launchers\windows\setup_windows.bat -Repair
.\launchers\windows\setup_windows.bat -Recreate
```

기본 setup도 Qt DLL 검증 실패 시 잠금된 PySide6 runtime을 한 번 자동 복구한다. `-Recreate`는
프로젝트 안의 생성된 `.venv`만 다시 만들며 데이터셋과 라벨은 건드리지 않는다.
PowerShell 앞에 `(base)`가 표시되어도 Windows setup/run 스크립트는 Conda Qt DLL 경로를
격리한다. 다만 `.venv`를 만들 공식 python.org CPython 3.12 64-bit는 별도로 설치되어 있어야 한다.

## Linux

- 최초 설치 또는 의존성 갱신: `linux/setup_linux.sh`
- 라벨링 도구 실행: `linux/run_linux.sh`

`windows/run_calibration.bat`과 `linux/run_calibration.sh`는 calibration 편집 기능용 실행
파일이다. `legacy/run_merged_sample.bat`은 예전 merged 샘플 전용이므로 일반 데이터셋에는
사용하지 않는다.

개발·검증·패키징 자동화는 저장소 루트가 아니라 `scripts/`와 `packaging/`에서 관리한다.
