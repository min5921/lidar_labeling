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
- 데이터셋의 `dataset.json`, calibration fingerprint, `sync/frames.jsonl`

runtime lock은 기준 최소 버전인 Python 3.10과 일반 개발 버전인 Python 3.12에서 함께 설치
가능한 버전으로 유지한다.

가상환경과 source code만 PC마다 설치한다. 원본 MCAP/YAML, 변환 데이터셋, 작업 라벨과 export
결과는 저장소 밖에서 관리한다.

## 2. 공통 준비

저장소를 clone하거나 실험실 파일 서버에서 전체 소스 폴더를 받는다.

```text
https://github.com/min5921/lidar_labeling.git
```

Python은 64-bit 3.10 이상을 설치한다. 처음 환경을 만들 때는 PyPI package 다운로드를 위한
인터넷 또는 실험실 내부 package mirror가 필요하다.

## 3. Windows venv

저장소 루트에서 `setup_windows.bat`을 더블클릭한다. 스크립트는 다음 작업을 수행한다.

1. Python 3.10 이상 탐색
2. `.venv` 생성
3. 고정 runtime package 설치
4. 프로젝트 editable 설치
5. package 버전과 기본 설정 검증

설치 후 `run_windows.bat`을 더블클릭한다. dataset 경로를 직접 전달할 수도 있다.

```powershell
.\run_windows.bat E:\one_chip_converted
```

Python Launcher나 PATH 대신 특정 Python 실행 파일을 지정하려면 다음처럼 실행한다.

```powershell
.\setup_windows.bat -PythonCommand C:\Python310\python.exe
```

## 4. Linux venv

Ubuntu 22.04 계열에서 Qt/OpenGL 시스템 라이브러리를 먼저 준비한다.

```bash
sudo apt-get update
sudo apt-get install python3 python3-venv libegl1 libgl1 libxkbcommon-x11-0 libxcb-cursor0
```

저장소 루트에서 실행 권한을 확인하고 setup과 run을 실행한다.

```bash
chmod +x setup_linux.sh run_linux.sh
./setup_linux.sh
./run_linux.sh
```

특정 Python을 쓰려면 setup에 환경 변수를 지정한다.

```bash
PYTHON_BIN=python3.12 ./setup_linux.sh
```

dataset 경로를 직접 전달할 수도 있다.

```bash
./run_linux.sh /data/one_chip_converted
```

## 5. Conda 대안

Windows PowerShell 또는 Linux shell에서 같은 순서로 실행한다.

```text
conda create --name lidar-label-tool python=3.10 pip
conda activate lidar-label-tool
python -m pip install --requirement requirements-bootstrap-lock.txt
python -m pip install --requirement requirements-lock.txt
python -m pip install --no-build-isolation --no-deps --editable .
python scripts/verify_source_environment.py
python -m lidar_label_tool gui
```

Conda 환경에서도 PySide6 등 runtime package는 `requirements-lock.txt`에 따라 pip로 설치한다.
venv와 Conda 환경을 한 실행에서 섞지 않는다.

## 6. 원본 변환과 경로

경로는 코드에 고정하지 않는다. GUI 첫 화면에서 source와 output을 선택하거나 CLI 인자로
지정한다.

```powershell
.\.venv\Scripts\python.exe scripts\convert_one_chip_dataset.py `
  --source E:\one_chip `
  --output E:\one_chip_converted `
  --timestamp-source header `
  --sync-tolerance-ms 70
```

Linux:

```bash
./.venv/bin/python scripts/convert_one_chip_dataset.py \
  --source /data/one_chip \
  --output /data/one_chip_converted \
  --timestamp-source header \
  --sync-tolerance-ms 70
```

재동기화는 기존 이미지와 포인트를 다시 추출하지 않고 `--sync-only-existing`을 추가한다.
실행 전 `sync/frames.jsonl`을 백업하고 camera sample 반복/점프 QA를 확인한다.

## 7. 설치 검증

Windows:

```powershell
.\.venv\Scripts\python.exe scripts\verify_source_environment.py
.\.venv\Scripts\python.exe -m lidar_label_tool preflight E:\one_chip_converted
```

Linux:

```bash
./.venv/bin/python scripts/verify_source_environment.py
./.venv/bin/python -m lidar_label_tool preflight /data/one_chip_converted
```

환경 검사는 Python 버전, 모든 고정 runtime package 버전, 프로젝트 import, 기본 설정 JSON을
검사한다. Preflight는 데이터셋 구조, point/image, sync, calibration과 작업 라벨을 검사한다.

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

```text
git pull
```

의존성 또는 프로젝트 코드가 바뀔 수 있으므로 setup을 다시 실행한다. 기존 `.venv`를 재사용하며
고정 package 버전과 editable project 설치를 최신 상태로 맞춘다.

## 10. 다른 PC 전달 체크리스트

- 같은 commit 또는 태그의 source인지 확인
- Python 3.10 이상 64-bit인지 확인
- setup 종료 시 `[OK]` 환경 검사가 출력되는지 확인
- dataset을 저장소 밖의 읽기/쓰기 가능한 경로에 배치
- `preflight` 종료 코드와 error/warning 확인
- Calibration reference frame과 fingerprint 확인
- frame 2991~3005처럼 알려진 구간의 camera sample 증가 확인
- GUI에서 좌/우 camera projection 확인
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
