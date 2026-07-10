# 포터블 배포 브랜치 체크리스트

이 문서는 Python과 개발 환경이 없는 다른 Windows PC에서 LiDAR Label Tool을 실행하기 위한
배포 준비와 검수 기준을 정리한다. 배포 관련 변경은 `codex/portable-distribution` 브랜치에서
진행한다.

## 1. 배포 목표

다른 PC에는 다음 두 묶음만 전달한다.

```text
LiDARLabelTool/          # PyInstaller one-folder 앱
one_chip_converted/      # 변환 완료 device-centric dataset
```

다른 PC에서 요구하지 않는 것:

- Python 설치
- `.venv` 생성
- `pip install`
- ROS2, MCAP 변환 패키지 설치
- 원본 `E:\one_chip\rosbags` 접근

원본 MCAP/YAML 변환은 개발/변환 PC에서 수행하고, 라벨링 PC에는 변환 완료 dataset만 전달한다.

## 2. 현재 확인 상태

2026-07-10 기준:

- 현재 브랜치: `codex/portable-distribution`
- 기준 커밋: `697e276 feat: add one chip conversion workflow and floor fitting`
- `ruff check .`: 통과
- `pytest`: 111 passed
- 빌드 venv `ruff check`: 통과
- PyInstaller one-folder build: 성공
- 빌드 Python: 3.12.13
- `.build/windows-portable-venv-py312`: 생성됨
- `dist/LiDARLabelTool/LiDARLabelTool.exe`: 생성됨
- 최종 분리 배포 폴더: `release_packages/LiDARLabelTool_Portable_20260710_r6/`
- 최종 배포 ZIP: `release_packages/LiDARLabelTool_Portable_20260710_r6.zip`
- 최종 ZIP size: `82994162` bytes
- 최종 ZIP SHA-256: `55477CBF38BC9E3E7B6C57EAE65BF33945213C695DA50DDC86543DFB608336B3`
- 로컬 198-frame Waymo dataset preflight: errors 0, warnings 0
- portable GUI direct-open smoke: 정상 종료 코드 0, crash log/lock 잔여 없음
- `E:\one_chip_converted` preflight/calibration: 이전 r4 검수에서 errors 0, warnings 0
- 현재 세션의 `E:` 드라이브: 연결되지 않아 r6에서 one_chip 실데이터 재검증 보류
- Python 미설치 별도 clean PC 최종 인증: 보류

`outputs/`는 진행 요약 자료로 보이며 포터블 앱 배포 산출물과 직접 관련되지 않으므로 배포 브랜치
작업에서 별도 판단 전에는 건드리지 않는다.

## 3. 빌드 PC 사전 조건

- Windows 10/11 64-bit
- Python 3.10 이상 또는 Python Launcher `py`
- 최초 빌드 시 인터넷 연결
- PowerShell 5.1 이상
- 충분한 디스크 공간

빌드 명령:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\packaging\build_windows_portable.ps1
```

현재 PC처럼 Python Launcher가 정확한 3.10 런타임을 찾지 못하면, 검증된 Python 실행 파일을
명시한다.

```powershell
.\packaging\build_windows_portable.ps1 `
  -PythonCommand .\.venv\Scripts\python.exe `
  -VenvDirectory .build\windows-portable-venv-py312
```

반복 빌드에서 테스트를 이미 별도 통과시킨 경우에만 다음 옵션을 사용할 수 있다.

```powershell
.\packaging\build_windows_portable.ps1 -SkipTests
```

기존 build venv 의존성을 그대로 쓸 때는 `-SkipDependencyInstall`을 함께 사용할 수 있다.

## 4. 빌드 산출물

기대 산출물:

```text
dist/
└─ LiDARLabelTool/
   ├─ LiDARLabelTool.exe
   ├─ _internal/
   └─ ...
```

주의:

- `LiDARLabelTool.exe` 하나만 복사하지 않는다.
- `dist/LiDARLabelTool/` 폴더 전체가 배포 단위다.
- 대용량 dataset은 앱 폴더에 포함하지 않는다.
- `local_data/`, `dataset/`, `datasets/`, `E:\one_chip` 원본은 배포 앱에 넣지 않는다.

최종 전달용 폴더와 ZIP은 다음 명령으로 재현한다.

```powershell
.\packaging\package_windows_release.ps1 `
  -ReleaseName LiDARLabelTool_Portable_YYYYMMDD_rN `
  -DefaultDatasetPath E:\one_chip_converted
```

## 5. 로컬 빌드 후 검수

빌드 PC에서 먼저 확인한다.

```powershell
.\dist\LiDARLabelTool\LiDARLabelTool.exe
```

확인 항목:

- 앱이 실행되고 dataset 선택 창이 뜬다.
- `E:\one_chip_converted`를 열 수 있다.
- Point cloud가 표시된다.
- CAM_LEFT/CAM_RIGHT 이미지가 표시된다.
- frame 이동 시 이미지가 반복 정지하지 않고 자연스럽게 진행된다.
- 새 박스를 만들고 이동/크기/yaw/z/height 편집이 된다.
- 저장 후 재실행해 라벨이 유지된다.
- 같은 dataset을 두 앱에서 열 때 session lock 경고가 뜬다.

## 6. Dataset 검수

변환 완료 dataset에는 다음 구조가 있어야 한다.

```text
one_chip_converted/
├─ dataset.json
├─ conversion_report.json
├─ calibration/calibration.json
├─ lidar/*.bin
├─ cam_left/*.jpg
├─ cam_right/*.jpg
└─ sync/frames.jsonl
```

기존 변환 결과나 호환성 확인용 dataset은 `sensors/lidar/MERGED/frames` legacy 구조일 수 있다.
앱은 `dataset.json`의 `data_patterns`를 기준으로 읽으므로 두 구조 모두 열 수 있다.

현재 one_chip 기준 기대값:

- logical frame: 3754
- MERGED LiDAR BIN: 3754
- CAM_LEFT/CAM_RIGHT: 누락 sync 0
- sync 기준: `header_aligned`
- sync tolerance: 70 ms
- preflight: errors 0, warnings 0
- calibration verification: errors 0, warnings 0

검수 명령:

```powershell
.\packaging\one_chip_run_pack\00_preflight_one_chip.bat
.\packaging\one_chip_run_pack\07_verify_calibration.bat
```

## 7. 깨끗한 PC 검수

Python 없는 Windows PC 또는 VM에서 확인한다.

1. `dist/LiDARLabelTool/` 폴더 전체를 복사한다.
2. `one_chip_converted/` dataset을 별도 위치에 복사한다.
3. 한글/공백 경로에서 앱을 실행한다.
4. 한글/공백 경로의 dataset을 연다.
5. 3D view, BEV, side view, camera view를 확인한다.
6. 라벨 저장 후 재실행하여 값이 유지되는지 확인한다.
7. 강제 종료 후 recovery snapshot 동작을 확인한다.
8. Windows SmartScreen 또는 백신 경고 여부를 기록한다.
9. 원격 데스크톱 환경이면 OpenGL 표시 문제 여부를 별도 기록한다.

권장 테스트 경로:

```text
D:\라벨링 테스트\LiDARLabelTool\
D:\데이터셋 테스트\one chip converted\
```

## 8. 배포 중단 기준

다음 중 하나라도 발생하면 배포를 중단하고 수정한다.

- Python 없는 PC에서 앱 실행 실패
- dataset 선택 창이 뜨지 않음
- point cloud 또는 camera image가 표시되지 않음
- 3D view가 검은 화면으로 고정됨
- 저장 후 라벨 JSON이 손상됨
- 같은 dataset 동시 실행 시 session lock이 동작하지 않음
- calibration verification error 발생
- preflight error 또는 예상하지 못한 warning 발생
- 한글/공백 경로에서 dataset open/save 실패

## 9. 릴리스 메모에 남길 것

- 빌드 날짜
- Git branch와 commit hash
- Python 버전
- PyInstaller 버전
- Windows 버전
- 테스트한 dataset 이름과 frame 수
- preflight 결과
- calibration verification 결과
- 깨끗한 PC 검수 결과
- 알려진 제한
