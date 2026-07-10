# 포터블 배포 버전 생성 기록

## 배포 폴더

이번 배포 작업은 기존 개발 폴더와 분리해 다음 위치에 만들었다. 최종 검수본은 `r6`이다.

```text
release_packages/LiDARLabelTool_Portable_20260710_r6/
```

구성:

```text
LiDARLabelTool_Portable_20260710_r6/
├─ LiDARLabelTool.exe
├─ _internal/
├─ datasets/
├─ manuals/
├─ Start_LiDAR_Label_Tool.bat
├─ Open_Configured_Dataset.bat
├─ BUILD_INFO.txt
└─ README_FIRST.md
```

## 빌드 명령

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows_portable.ps1 `
  -PythonCommand .\.venv\Scripts\python.exe `
  -VenvDirectory .build\windows-portable-venv-py312 `
  -SkipTests -SkipDependencyInstall
```

```powershell
powershell -ExecutionPolicy Bypass -File packaging\package_windows_release.ps1 `
  -ReleaseName LiDARLabelTool_Portable_20260710_r6 `
  -DefaultDatasetPath E:\one_chip_converted
```

## 결과

- `pytest`: 111 passed
- `ruff check`: 통과
- PyInstaller one-folder build: 성공
- 최종 r6 ZIP: `release_packages/LiDARLabelTool_Portable_20260710_r6.zip`
- 최종 r6 ZIP size: `82994162` bytes
- 최종 r6 ZIP SHA-256: `55477CBF38BC9E3E7B6C57EAE65BF33945213C695DA50DDC86543DFB608336B3`
- 로컬 198-frame dataset preflight: errors 0, warnings 0
- r6 portable GUI direct-open smoke: 종료 코드 0, crash log 변화 없음, session lock 잔여 없음
- r6 `Start_LiDAR_Label_Tool.bat <dataset>` smoke: EXE 실행·정상 창 닫기·lock 정리 통과
- `E:\one_chip_converted`와 calibration은 r4에서 errors 0, warnings 0으로 검증했으나,
  현재 세션에는 `E:` 드라이브가 없어 r6 실데이터 재검증은 수행하지 못했다.
- Python 미설치 별도 clean Windows PC 최종 인증은 아직 필요하다.

수정 이력:

- `r1`: 최초 배포본. PyInstaller config 경로 문제로 실행 실패.
- `r2`: dataset 경로 인자와 crash log 추가. config 경로 문제 확인.
- `r3`: PyInstaller `_internal/configs/default.json` 경로 지원 후 실행 검수 통과.
- `r4`: `LiDARLabelTool.exe`를 배포 폴더 최상위로 이동해 사용자가 바로 실행 파일을 볼 수 있게 구성.
- `r5`: source/calibration 변경 감지, unknown field 보존, AppData crash log, 자동 패키징을 반영.
- `r6`: 최신 매뉴얼과 검수 기록을 패키지에 동기화한 최종본.

## 배포 원칙

다른 PC에는 포터블 앱 폴더와 변환 완료 dataset만 전달한다. 원본 MCAP/ROS bag 변환은 개발/변환
PC에서만 수행한다.
