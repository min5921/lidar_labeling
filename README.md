# LiDAR Label Tool

LiDAR point cloud를 보면서 3D bounding box를 생성·수정·저장하고, 선택적으로 camera image와
projection을 함께 확인하는 라벨링 도구입니다.

현재 기본 작업 흐름은 **범용 데이터셋 v2**입니다. 프로그램이 원본 폴더를 분석해
`dataset.json`, taxonomy와 frame index를 생성하므로 사용자가 JSON을 직접 작성할 필요가
없습니다. 기존 v1, Waymo와 one_chip 데이터는 호환·레거시 경로로 계속 지원합니다.

> 현재 개발·검증 브랜치는 `codex/v2`입니다. 새 PC에서는 이 브랜치를 명시해 받으세요.
> Python이 포함된 EXE 설치본은 아직 제공하지 않으며, 각 PC에 공식 Python을 설치한 뒤
> 프로젝트의 고정 가상환경으로 실행합니다.

## 핵심 동작 원칙

- 데이터셋에 여러 LiDAR 후보를 등록할 수 있지만, 한 라벨링 profile에서는 LiDAR 하나만
  사용합니다.
- 프로그램 안에서 여러 LiDAR를 자동으로 합치지 않습니다. 다른 LiDAR는 별도 profile로 열어
  독립적으로 라벨링합니다.
- profile마다 camera는 0개 또는 1개입니다.
- camera, timestamp 또는 calibration이 없어도 정상 LiDAR frame은 라벨링하고 저장할 수 있습니다.
- 동기화 실패나 이미지 누락 때문에 LiDAR frame을 제거하지 않습니다.
- 원본 point, image, timestamp와 source label은 수정하지 않습니다.
- 작업 라벨은 profile과 LiDAR별 폴더에 원자적으로 저장하므로 같은 frame ID도 서로 덮어쓰지
  않습니다.

## 새 Windows PC에 반드시 필요한 프로그램

다음 프로그램은 자동으로 포함되지 않으므로 먼저 설치해야 합니다.

| 필수 항목 | 현재 권장 기준 | 용도 |
|---|---|---|
| Windows | Windows 10 1809 이상 또는 Windows 11, 64-bit | Qt GUI 실행 |
| Git | Git for Windows 최신 안정판 | 소스 내려받기와 업데이트 |
| Python | **python.org 공식 CPython 3.12 64-bit** | 프로젝트 `.venv` 생성 |
| 인터넷 | 최초 설치 시 필요 | 고정된 Python package 다운로드 |
| 그래픽 환경 | OpenGL 지원 driver와 desktop 화면 | 3D point cloud 표시 |

Python 3.10 이상도 코드상 지원하지만, 새 Windows PC의 우선 검증 버전은 Python 3.12 64-bit입니다.

### Python 설치 시 주의사항

1. [Python 공식 Windows 다운로드](https://www.python.org/downloads/windows/)에서
   Python 3.12의 `Windows installer (64-bit)`를 받습니다.
2. 설치 첫 화면에서 `Add python.exe to PATH`를 선택합니다.
3. `Python Launcher`도 함께 설치합니다.
4. 설치가 끝나면 열려 있던 PowerShell을 모두 닫고 새 PowerShell을 엽니다.
5. 다음 명령이 `Python 3.12.x`를 출력하는지 확인합니다.

```powershell
py -3.12 --version
```

다음 상태는 공식 Python 설치가 완료된 것으로 보지 않습니다.

- PowerShell에 `(base)`만 표시되고 Conda Python만 설치된 상태
- `Python was not found ... Microsoft Store` 메시지만 나오는 상태
- Windows의 App execution alias만 켜져 있는 상태
- 다른 PC나 다른 폴더에서 `.venv`를 복사한 상태

Windows용 setup은 Conda의 Qt DLL 충돌을 막기 위해 Conda 환경을 격리합니다. 따라서 `(base)`가
표시되어 있어도 실행할 수 있지만, `.venv`를 만들 **공식 python.org CPython은 별도로 설치**되어
있어야 합니다.

## Windows 빠른 설치

### 1. 현재 v2 브랜치 받기

[Git for Windows](https://git-scm.com/download/win)를 설치한 뒤 프로젝트를 둘 폴더에서
PowerShell을 엽니다.

```powershell
cd C:\Lab
git clone --branch codex/v2 --single-branch https://github.com/min5921/lidar_labeling.git
cd lidar_labeling
```

GitHub에서 ZIP으로 받아도 됩니다. 이때 `pyproject.toml`, `README.md`, `launchers` 폴더가 같이
보이는 압축 해제 폴더가 프로젝트 루트입니다. 예전에 생성된 `.venv`는 함께 복사하지 않습니다.

### 2. 최초 환경 설치

탐색기에서 `launchers\windows\setup_windows.bat`을 더블클릭하거나 PowerShell에서 실행합니다.

```powershell
.\launchers\windows\setup_windows.bat
```

setup은 다음 작업을 자동으로 수행합니다.

1. 공식 64-bit Python 3.12 우선 탐색
2. 프로젝트 내부 `.venv` 생성
3. lock 파일에 고정된 package 설치
4. 프로젝트 설치
5. PySide6의 QtCore, QtGui, QtWidgets native DLL까지 실행 검증

설치 마지막에 다음 형식의 메시지가 나오면 정상입니다.

```text
[OK] LiDAR Label Tool source environment verified (...)
```

### 3. 프로그램 실행

```powershell
.\launchers\windows\run_windows.bat
```

평상시에는 setup을 다시 할 필요 없이 `run_windows.bat`만 실행하면 됩니다. 데이터셋 경로를
직접 넘길 수도 있습니다.

```powershell
.\launchers\windows\run_windows.bat "D:\data\my_dataset"
```

## 기존 Git 폴더 업데이트

먼저 `git status`에서 사용자가 수정한 코드가 없는지 확인합니다. 원본 데이터와 작업 라벨은
저장소 밖에 두는 것을 권장합니다.

```powershell
git fetch origin
git switch codex/v2
git pull --ff-only origin codex/v2
.\launchers\windows\setup_windows.bat
```

다른 PC에서 가져온 기존 `.venv` 또는 Conda Python으로 만든 `.venv`가 있다면 다음 명령으로
프로젝트 환경만 새로 만듭니다. 데이터셋과 라벨은 삭제하지 않습니다.

```powershell
.\launchers\windows\setup_windows.bat -Recreate
```

## Ubuntu Linux 설치

Ubuntu 22.04 이상과 Python 3.10 이상을 지원하며 Python 3.12를 권장합니다.

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv \
  libegl1 libgl1 libxkbcommon-x11-0 libxcb-cursor0

mkdir -p ~/lab
cd ~/lab
git clone --branch codex/v2 --single-branch https://github.com/min5921/lidar_labeling.git
cd lidar_labeling

chmod +x launchers/linux/setup_linux.sh launchers/linux/run_linux.sh
./launchers/linux/setup_linux.sh
./launchers/linux/run_linux.sh
```

특정 Python을 사용하려면 다음처럼 지정합니다.

```bash
PYTHON_BIN=python3.12 ./launchers/linux/setup_linux.sh
```

SSH terminal만 있는 서버에서는 GUI가 표시되지 않을 수 있습니다. OpenGL을 사용할 수 있는 로컬
desktop session 또는 올바르게 구성된 그래픽 전달 환경이 필요합니다.

## 범용 데이터셋 v2 입력 형식

### LiDAR

| 형식 | 지원 범위 | 사용자가 확인할 내용 |
|---|---|---|
| `.bin` | little-endian dense `float32` | 한 점의 전체 column 순서 |
| `.pcd` | PCD v0.7 ASCII 또는 uncompressed binary | header의 field와 실제 payload |

모든 LiDAR에는 `x`, `y`, `z`가 필요합니다. BIN은 일반적으로 column 이름을 파일 내부에 저장하지
않으므로 프로그램이 임의로 의미를 추측하지 않습니다. 예를 들어 한 점이
`x, y, z, intensity, reflectivity, velocity` 순서라면 구성 화면에 그 전체 순서를 정확히
입력해야 합니다.

LiDAR 후보가 여러 개라면 센서별로 폴더를 분리하는 것을 권장합니다.

### Camera

- 지원 형식: `.jpg`, `.jpeg`, `.png`
- 한 profile에 camera는 없음 또는 한 개만 선택합니다.
- 좌·우 영상이 이미 합성·보정된 이미지라면 논리 camera 한 개로 사용할 수 있습니다.
- 이미지가 있다는 사실만으로 3D projection calibration이 있다고 간주하지 않습니다.

### Timestamp와 동기화

다음 세 방식 중 하나를 선택합니다.

| 방식 | 필요한 입력 | 동작 |
|---|---|---|
| LiDAR만 사용 | LiDAR 파일 | 모든 LiDAR frame을 유지하고 camera를 연결하지 않음 |
| 같은 파일 stem | LiDAR와 image | `000001.bin`과 `000001.jpg`처럼 stem이 같은 파일 연결 |
| 가장 가까운 timestamp | LiDAR CSV와 camera CSV | tolerance 안에서 가장 가까운 image 연결 |

Timestamp CSV를 사용할 때 구성 화면의 항목은 다음 뜻입니다.

| 항목 | 의미 |
|---|---|
| Sample ID 컬럼 | CSV 행을 point/image 파일 stem과 연결하는 열 |
| Timestamp 컬럼 | 실제 동기화 계산에 사용할 정수 시간 열 |
| Timestamp 단위 | CSV 숫자의 단위: `ns`, `us`, `ms`, `s` |
| Clock domain | 시간 기준의 identity: 예를 들면 `bag`, `header`, `device` |
| Nearest tolerance | 두 sensor sample을 같은 frame으로 허용할 최대 시간 차이 |

두 sensor는 같은 clock domain을 사용해야 합니다. clock domain은 단위 변환이나 시간 offset이
아니며, 서로 다른 clock을 프로그램이 조용히 연결하지 않습니다. 내부 계산은 정수 nanosecond
정밀도를 유지합니다.

CSV 예시는 다음과 같습니다.

```csv
sample_id,timestamp_ns
000000,1778225784354747202
000001,1778225784454747202
```

### 권장 원본 폴더 예시

폴더명이 반드시 아래와 같을 필요는 없지만, 센서별로 분리하면 자동 탐색 결과를 확인하기 쉽습니다.

```text
my_dataset/
├─ lidar/
│  ├─ AEVA/
│  │  ├─ 000000.bin
│  │  └─ 000001.bin
│  └─ LIDAR_POINTS/
│     ├─ 000000.bin
│     └─ 000001.bin
├─ camera/
│  └─ HEAD_CAMERA/
│     ├─ 000000.jpg
│     └─ 000001.jpg
├─ timestamps/
│  ├─ AEVA.csv
│  ├─ LIDAR_POINTS.csv
│  └─ HEAD_CAMERA.csv
└─ calibration/                 # 선택 사항
```

## 프로그램에서 처음 데이터셋 구성

1. `run_windows.bat` 또는 `run_linux.sh`를 실행합니다.
2. 첫 화면에서 `데이터 폴더/데이터셋 열기`를 선택합니다.
3. `dataset.json`이 없는 원본 데이터 폴더를 선택합니다.
4. 탐색된 LiDAR 후보 중 사용할 센서를 하나 이상 선택합니다.
5. 각 LiDAR의 point columns와 coordinate frame을 입력합니다.
6. `meter / x-forward / y-left / z-up / +z yaw` 계약을 확인합니다.
7. camera는 없음 또는 한 개를 선택합니다.
8. 동기화 방식과 필요한 timestamp 설정을 입력합니다.
9. 원본 폴더가 읽기 전용이면 `구성/라벨 폴더`를 별도의 쓰기 가능한 위치로 선택합니다.
10. `구성 분석`에서 frame 수, match/unmatched, camera reuse와 최대 시간 차이를 확인합니다.
11. 결과가 맞으면 `검증 결과로 생성`을 누릅니다.

분석 단계에서는 파일을 생성하지 않습니다. 분석 후 설정이나 원본이 바뀌면 다시 분석해야 하며,
schema·payload·frame binding 검사를 통과한 결과만 활성화합니다. 실패하거나 취소하면 기존 구성과
원본은 그대로 유지됩니다.

## 생성되는 파일

```text
<configuration-root>/
├─ dataset.json
├─ generations/
│  └─ generation-000001/
│     ├─ taxonomy.json
│     └─ sync/
│        ├─ aeva_profile.frames.jsonl
│        └─ lidar_points_profile.frames.jsonl
└─ annotations/
   └─ lidar_label_tool/
      ├─ aeva_profile/aeva/<frame_id>.json
      └─ lidar_points_profile/lidar_points/<frame_id>.json
```

- `dataset.json`: sensor, profile, 좌표계와 현재 활성 generation을 기록하는 manifest
- `*.frames.jsonl`: LiDAR frame 순서와 선택적 camera 연결을 확정한 index
- `taxonomy.json`: 안정적인 class ID, 표시 이름, 색상과 기본 box 크기
- `annotations/...`: profile과 LiDAR별로 분리된 작업 라벨

이 파일들은 프로그램이 생성하고 검증합니다. 일반 사용자가 직접 편집할 필요가 없습니다.

## 여러 LiDAR를 사용하는 방법

초기 구성에서 여러 LiDAR를 선택하면 LiDAR마다 독립 profile이 생성됩니다. 데이터셋을 열 때 이번
세션에서 사용할 profile 하나를 선택합니다. 다른 LiDAR로 작업하려면 데이터셋을 다시 열고 다른
profile을 선택합니다.

이미 데이터셋을 만든 뒤 새 LiDAR를 추가할 때는 삭제하고 다시 만들 필요가 없습니다.

1. 첫 화면에서 `범용 v2 LiDAR profile 추가`를 선택합니다.
2. 기존 `dataset.json`이 있는 구성 폴더를 선택합니다.
3. 새 LiDAR의 columns, coordinate frame과 sync 설정을 확인합니다.
4. `변경 분석` 결과를 확인한 뒤 `새 profile 추가`를 실행합니다.

기존 dataset ID, profile, generation과 라벨은 보존됩니다.

## 범용 v2 재동기화

이미지 연결 방식이나 tolerance를 바꾸려면 첫 화면의 `범용 v2 재동기화`를 사용합니다. 이 기능은
point와 image 원본을 변환하지 않고 새 frame-index generation만 만들어 원자적으로 활성화합니다.
LiDAR frame의 ID, 순서와 point 경로는 변경하지 않으며 이전 generation과 라벨도 보존합니다.

## 데이터 검사와 CLI

GUI 첫 화면의 `데이터셋 검사`를 권장합니다. CLI로도 읽기 전용 검사를 실행할 수 있습니다.

Windows:

```powershell
.\.venv\Scripts\python.exe -m lidar_label_tool validate-v2 "D:\data\dataset_config"
.\.venv\Scripts\python.exe -m lidar_label_tool preflight "D:\data\dataset_config"
```

Linux:

```bash
./.venv/bin/python -m lidar_label_tool validate-v2 /data/dataset_config
./.venv/bin/python -m lidar_label_tool preflight /data/dataset_config
```

검사 종료 코드는 `0` 정상, `1` warning, `2` error입니다. warning은 내용을 확인한 뒤 LiDAR 작업을
계속할 수 있는 경우가 있지만 error는 먼저 수정해야 합니다.

## 라벨링과 저장 안전

- `Ctrl+S`로 현재 frame의 작업 라벨을 저장합니다.
- 1000개 단위로 나눈 연속 폴더는 다음 폴더의 첫 frame에서 `이전 폴더의 객체 가져오기…`로
  이전 마지막 작업 JSON의 객체들을 같은 ID로 가져올 수 있습니다. 같은 LiDAR·좌표계에서만
  사용하며 기존 ID는 덮어쓰지 않습니다. 가져온 위치는 현재 포인트에 맞춰 조정합니다.
- source label은 먼저 불러올 수 있지만 일반 저장으로 원본을 덮어쓰지 않습니다.
- 저장 전 revision과 fingerprint를 비교하여 다른 프로그램의 변경을 조용히 덮어쓰지 않습니다.
- 임시 파일 검증과 atomic replace를 사용하고 직전 `.bak`을 유지합니다.
- camera 또는 calibration 문제는 projection만 비활성화하며 LiDAR 라벨 저장은 계속할 수 있습니다.
- export는 일반 저장과 분리되어 있으며 첫 화면의 `라벨 내보내기`에서 명시적으로 실행합니다.

상세 조작법은 [GUI 사용자 매뉴얼](docs/USER_MANUAL.md)을 확인하세요.

## LiDAR–camera calibration 편집기

Windows:

```powershell
.\launchers\windows\run_calibration.bat
```

Linux:

```bash
./launchers/linux/run_calibration.sh
```

편집기는 point와 3D box를 camera image에 투영하면서 6DoF와 intrinsic을 조정할 수 있습니다.
원본 calibration을 덮어쓰지 않고 `calibration/adjusted` 아래의 새 JSON으로 저장합니다. 조정본을
저장하는 것만으로 dataset profile의 활성 calibration이 자동 변경되지는 않습니다.

## one_chip 레거시 기능

다음 기능은 특정 `calibration + rosbags` 취득 구조 전용이며 범용 데이터셋을 만들 때 사용하지
않습니다.

- one_chip MCAP/ROS bag 변환
- one_chip 기존 결과 재동기화
- one_chip Calibration JSON 생성·검증

첫 화면의 접힌 `고급 도구 — one_chip 레거시 전용` 영역에 보존되어 있습니다. 필요한 경우
[one_chip 변환 매뉴얼](docs/20_ONE_CHIP_CONVERSION_MANUAL.md)을 따르세요.

## 자주 발생하는 문제

| 증상 | 원인과 해결 |
|---|---|
| `Official 64-bit CPython ... was not found` | python.org의 Python 3.12 64-bit와 Python Launcher를 설치하고 새 PowerShell에서 `py -3.12 --version`을 확인합니다. |
| `Python was not found ... Microsoft Store` | 공식 Python이 없고 실행 alias만 활성화된 상태입니다. Microsoft Store 안내 대신 python.org installer를 사용합니다. |
| `(base)`가 표시됨 | 최신 launcher가 Conda Qt 경로를 격리하므로 표시 자체는 괜찮습니다. 다만 공식 Python은 별도로 필요합니다. |
| 기존 `.venv`가 Conda 기반이라고 나옴 | `.\launchers\windows\setup_windows.bat -Recreate`를 실행합니다. |
| `QtCore` 또는 `QtWidgets` DLL load failed | 먼저 `setup_windows.bat -Repair`, 계속 실패하면 `-Recreate`를 실행합니다. 이후 Microsoft Visual C++ x64 runtime과 Windows 버전을 확인합니다. |
| `adapter_open_failed: expected dataset.json ...` | 최신 `codex/v2`를 사용하고 첫 화면에서 JSON이 없는 원본 폴더를 선택해 범용 구성 마법사를 실행합니다. JSON을 손으로 만들지 않습니다. |
| 구성 생성 버튼이 비활성화됨 | 선택한 모든 LiDAR의 전체 point columns와 좌표 계약 확인 여부를 점검하고 `구성 분석`을 다시 실행합니다. |
| timestamp match가 0개임 | 두 CSV의 sample ID/timestamp 컬럼, 단위, clock domain과 tolerance를 확인합니다. |
| 다른 LiDAR로 라벨링하고 싶음 | 데이터셋을 다시 열어 다른 profile을 선택하거나 `범용 v2 LiDAR profile 추가`를 사용합니다. |
| package 다운로드 실패 | 인터넷, proxy, 방화벽 또는 같은 OS/Python용 내부 wheelhouse를 확인합니다. |

Qt DLL 오류가 계속되면 [Microsoft Visual C++ x64 Runtime](https://aka.ms/vc14/vc_redist.x64.exe)을
설치 또는 복구하고 `winver`에서 Windows 10 1809 이상 또는 Windows 11 x64인지 확인합니다.

## 저장소 구조

```text
lidar_labeling/
├─ launchers/       # 사용자용 Windows/Linux 설치·실행 파일
├─ src/             # 애플리케이션, domain, service, adapter, UI
├─ schemas/         # dataset/label/calibration JSON Schema
├─ configs/         # 기본 프로그램 설정
├─ scripts/         # 변환·검증·개발 보조 스크립트
├─ tests/           # 단위·통합 테스트
└─ docs/            # 계약, 설치, 사용 및 검수 문서
```

`.venv`, 원본 데이터, 생성된 dataset, 작업 라벨과 export 결과는 Git에 포함하지 않습니다.

## 상세 문서

- [문서 전체 안내와 우선순위](docs/README.md)
- [Windows/Linux 소스 설치와 복구](docs/31_LAB_SOURCE_SETUP.md)
- [범용 데이터셋 v2 구성·사용 가이드](docs/33_GENERIC_DATASET_SETUP_GUIDE.md)
- [GUI 사용자 매뉴얼](docs/USER_MANUAL.md)
- [범용 데이터셋 v2 확정 계약](docs/32_GENERIC_DATASET_V2_CONTRACT.md)
- [Preflight와 QA](docs/18_PREFLIGHT_AND_QA.md)
- [one_chip 변환 매뉴얼](docs/20_ONE_CHIP_CONVERSION_MANUAL.md)
