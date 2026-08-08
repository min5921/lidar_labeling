# 실험실 내부 소스 설치와 운영

## 1. 운영 기준

LiDAR Label Tool은 Windows와 Linux 모두 저장소 소스에서 실행한다. Python 미설치용 EXE/ELF,
PyInstaller, GitHub Release 실행 파일은 현재 운영 경로가 아니다.

고정하는 항목:

- Python 3.10 이상
- `requirements-bootstrap-lock.txt`의 pip/build tool 버전
- `requirements-lock.txt`의 GUI/validation runtime package 버전
- `requirements-dev-lock.txt`의 테스트/정적 검사 package 버전
- 동일한 저장소 commit
- 데이터셋의 `dataset.json`, calibration fingerprint와 v1 `sync/frames.jsonl` 또는 v2
  `generations/<generation>/sync/<profile>.frames.jsonl`

runtime lock은 기준 최소 버전인 Python 3.10과 일반 개발 버전인 Python 3.12에서 함께 설치
가능한 버전으로 유지한다.

가상환경과 source code만 PC마다 설치한다. 원본 MCAP/YAML, 변환 데이터셋, 작업 라벨과 export
결과는 저장소 밖에서 관리한다.

## 2. 공통 준비

현재 개발·검증 브랜치를 명시해 저장소를 clone하거나 실험실 파일 서버에서 전체 소스 폴더를
받는다.

```powershell
git clone --branch codex/v2 --single-branch https://github.com/min5921/lidar_labeling.git
cd lidar_labeling
```

Python은 python.org의 공식 64-bit CPython 3.10 이상을 설치한다. 새 Windows PC의 우선 검증
버전은 64-bit Python 3.12다. 처음 환경을 만들 때는 PyPI package 다운로드를 위한 인터넷 또는
실험실 내부 package mirror가 필요하다. 다른 PC에서 만든 `.venv`는 복사하지 않는다. PowerShell
앞에 `(base)`가 표시되는 Conda Python을 일반 `.venv`의 기반으로 사용하지 않는다.

Windows에서는 [python.org Windows 다운로드](https://www.python.org/downloads/windows/)의
`Windows installer (64-bit)`를 사용하고 `Add python.exe to PATH`와 `Python Launcher`를
선택한다. 설치 후 모든 PowerShell을 닫고 새 창에서 확인한다.

```powershell
py -3.12 --version
```

`Python was not found ... Microsoft Store` 또는 `py 명령을 찾을 수 없습니다`가 나오면 공식
Python 설치가 완료되지 않은 것이다. App execution alias나 Conda `(base)`만으로 대체하지 않는다.

## 3. Windows venv

`launchers/windows/setup_windows.bat`을 더블클릭한다. 스크립트는 다음 작업을 수행한다.

1. python.org의 64-bit Python 3.12 우선 탐색 후 다른 3.10 이상 공식 CPython 탐색
2. `.venv` 생성
3. 고정 runtime package 설치
4. 프로젝트 editable 설치
5. package 버전, 기본 설정, `PySide6.QtCore/QtGui/QtWidgets` native DLL 검증

setup과 Windows run 스크립트는 활성 Conda의 `Library/bin` 및 Qt 관련 환경 변수를 실행 PATH에서
제거한다. Conda Python으로 만들어진 기존 `.venv`는 재사용하지 않고 공식 CPython 설치 후
`-Recreate`를 요구한다. `py` 명령을 찾을 수 없고 `(base)`만 표시된다면
`https://www.python.org/downloads/windows/`에서 Python 3.12 64-bit와 Python Launcher를 먼저
설치한다.

성공하면 마지막에 다음 형식이 출력된다.

```text
[OK] LiDAR Label Tool source environment verified (...)
```

Qt DLL 검증이 실패하면 setup은 잠금된 PySide6·Essentials·Addons·shiboken6를 cache 없이 한 번
강제 재설치하고 다시 검사한다. 기존 환경을 명시적으로 복구하거나 완전히 다시 만들려면 저장소
루트의 PowerShell에서 다음을 실행한다.

```powershell
.\launchers\windows\setup_windows.bat -Repair
.\launchers\windows\setup_windows.bat -Recreate
```

`-Recreate`는 프로젝트 안의 생성물 `.venv`만 삭제한 뒤 다시 만든다. 데이터셋, 작업 라벨,
설정 파일은 삭제하지 않는다. 그래도 `QtWidgets` DLL 오류가 나면 Microsoft Visual C++ x64
runtime을 설치 또는 복구하고 `winver`에서 Windows 10 1809 이상 또는 Windows 11 x64인지
확인한다.

설치 후 `launchers/windows/run_windows.bat`을 더블클릭한다. dataset 경로를 직접 전달할 수도
있다.

```powershell
.\launchers\windows\run_windows.bat "D:\data\my_dataset"
```

Python Launcher나 PATH 대신 특정 Python 실행 파일을 지정하려면 다음처럼 실행한다.

```powershell
.\launchers\windows\setup_windows.bat -PythonCommand C:\Python312\python.exe
```

## 4. Linux venv

Ubuntu 22.04 계열에서 Qt/OpenGL 시스템 라이브러리를 먼저 준비한다.

```bash
sudo apt-get update
sudo apt-get install python3 python3-venv libegl1 libgl1 libxkbcommon-x11-0 libxcb-cursor0
```

저장소 루트에서 실행 권한을 확인하고 setup과 run을 실행한다.

```bash
chmod +x launchers/linux/setup_linux.sh launchers/linux/run_linux.sh
./launchers/linux/setup_linux.sh
./launchers/linux/run_linux.sh
```

특정 Python을 쓰려면 setup에 환경 변수를 지정한다.

```bash
PYTHON_BIN=python3.12 ./launchers/linux/setup_linux.sh
```

dataset 경로를 직접 전달할 수도 있다.

```bash
./launchers/linux/run_linux.sh /data/my_dataset
```

## 5. Conda 고급 대안

Windows PowerShell 또는 Linux shell에서 같은 순서로 실행한다.

```text
conda create --name lidar-label-tool python=3.12 pip
conda activate lidar-label-tool
python -m pip install --requirement requirements-bootstrap-lock.txt
python -m pip install --requirement requirements-lock.txt
python -m pip install --no-build-isolation --no-deps --editable .
python scripts/verify_source_environment.py
python -m lidar_label_tool gui
```

Conda 환경에서도 PySide6 등 runtime package는 `requirements-lock.txt`에 따라 pip로 설치한다.
이 대안을 선택했다면 `setup_windows.bat`이나 `.venv`용 run 스크립트를 사용하지 않고, 활성화한
전용 Conda 환경에서 `python -m lidar_label_tool gui`로 실행한다. venv와 Conda 환경을 한 실행에서
섞지 않는다. 새 Windows PC의 기본 설치 및 검증 경로는 이 대안이 아니라 공식 Python 기반
`.venv`다.

## 6. 범용 데이터 구성과 one_chip 레거시

경로는 코드에 고정하지 않는다. GUI 첫 화면의 `데이터 폴더/데이터셋 열기`에서
`dataset.json`이 없는 BIN/PCD 원본 폴더를 선택하면 범용 v2 구성 화면이 열린다. LiDAR
point columns·coordinate frame, 선택적 camera, sync 방식과 timestamp column/unit/clock
domain을 확인한 뒤 `구성 분석`과 `검증 결과로 생성`을 순서대로 실행한다.

여러 LiDAR 후보는 profile별로 분리되며 한 세션에서 하나만 활성화한다. 이미 만든 v2에 다른
LiDAR를 추가할 때는 `범용 v2 LiDAR profile 추가`, camera 연결을 다시 만들 때는
`범용 v2 재동기화`를 사용한다. 자세한 절차는 `docs/33_GENERIC_DATASET_SETUP_GUIDE.md`를
따른다.

아래 CLI는 특정 `calibration + rosbags` 구조를 위한 one_chip 레거시 도구다. 일반 BIN/PCD
폴더에는 사용하지 않는다.

```powershell
.\.venv\Scripts\python.exe scripts\convert_one_chip_dataset.py `
  --source E:\one_chip `
  --output E:\one_chip_converted `
  --timestamp-source header_aligned `
  --sync-tolerance-ms 70
```

Linux:

```bash
./.venv/bin/python scripts/convert_one_chip_dataset.py \
  --source /data/one_chip \
  --output /data/one_chip_converted \
  --timestamp-source header_aligned \
  --sync-tolerance-ms 70
```

재동기화는 기존 이미지와 포인트를 다시 추출하지 않고 `--sync-only-existing`을 추가한다.
실행 전 `sync/frames.jsonl`을 백업하고 camera sample 반복/점프 QA를 확인한다.

## 7. 설치 검증

Windows:

```powershell
.\.venv\Scripts\python.exe scripts\verify_source_environment.py
.\.venv\Scripts\python.exe -m lidar_label_tool validate-v2 "D:\data\my_dataset"
.\.venv\Scripts\python.exe -m lidar_label_tool preflight "D:\data\my_dataset"
```

Linux:

```bash
./.venv/bin/python scripts/verify_source_environment.py
./.venv/bin/python -m lidar_label_tool validate-v2 /data/my_dataset
./.venv/bin/python -m lidar_label_tool preflight /data/my_dataset
```

환경 검사는 Python 버전, 모든 고정 runtime package 버전, 프로젝트 import, 기본 설정 JSON과
PySide6/Qt native DLL import를 검사한다. Preflight는 데이터셋 구조, point/image, sync,
calibration과 작업 라벨을 검사한다.

## 8. 개발 검수

코드를 수정한 PC에서는 다음 검사를 실행한다.

Windows:

```powershell
.\.venv\Scripts\python.exe -m pip install --requirement requirements-dev-lock.txt
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
```

Linux는 실행 파일 경로만 `./.venv/bin/python`으로 바꾼다. GitHub Actions의
`Test source environments`도 Windows Server 2022와 Ubuntu 22.04에서 같은 검사를 수행한다.

## 9. 업데이트

작업 라벨과 dataset을 백업한 뒤 source를 업데이트한다.

```powershell
git fetch origin
git switch codex/v2
git pull --ff-only origin codex/v2
```

의존성 또는 프로젝트 코드가 바뀔 수 있으므로 setup을 다시 실행한다. 기존 `.venv`를 재사용하며
고정 package 버전과 editable project 설치를 최신 상태로 맞춘다.

## 10. 다른 PC 전달 체크리스트

- 같은 commit 또는 태그의 source인지 확인
- Windows는 공식 Python 3.12 64-bit와 `py -3.12 --version` 확인
- setup 종료 시 `[OK]` 환경 검사가 출력되는지 확인
- dataset을 저장소 밖의 읽기/쓰기 가능한 경로에 배치
- 범용 v2는 profile당 활성 LiDAR 하나, camera 0~1개인지 확인
- BIN 전체 point columns, coordinate frame, timestamp column/unit/clock domain 확인
- `preflight` 종료 코드와 error/warning 확인
- Calibration reference frame과 fingerprint 확인; 없을 때도 LiDAR 저장 가능한지 확인
- nearest sync의 match/unmatched/reuse/max delta 확인
- 선택 camera projection 확인
- 테스트 프레임 저장 후 재실행하여 box ID와 값 유지 확인

## 11. 오프라인 설치

인터넷이 없는 실험실 PC에는 운영체제와 Python minor version이 같은 연결된 PC에서 wheel을 먼저
수집한다.

```text
python -m pip download --requirement requirements-bootstrap-lock.txt --dest wheelhouse
python -m pip download --requirement requirements-lock.txt --dest wheelhouse
```

`wheelhouse`와 저장소를 대상 PC로 옮긴 뒤 해당 가상환경에서 설치한다.

```text
python -m pip install --no-index --find-links wheelhouse --requirement requirements-bootstrap-lock.txt
python -m pip install --no-index --find-links wheelhouse --requirement requirements-lock.txt
python -m pip install --no-build-isolation --no-deps --editable .
```

Windows wheel을 Linux에 사용하거나 Python 3.10용 wheel을 다른 호환되지 않는 Python에 사용하면
안 된다.
