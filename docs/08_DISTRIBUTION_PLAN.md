# 실험실 내부 운영 계획

## 목표

LiDAR Label Tool은 불특정 외부 사용자가 아니라 Windows/Linux 실험실 PC에서 운영한다.
Python 미설치 단일 실행 파일보다 source commit과 고정 dependency를 재현하는 것을 우선한다.
데이터셋은 저장소에 넣지 않고 사용자가 외부 폴더를 선택한다.

## 기준 환경

- Windows 10/11 x64
- Ubuntu 22.04 이상 x86_64
- Python 3.10 이상 64-bit
- 프로젝트별 `.venv` 또는 독립 Conda 환경
- `requirements-lock.txt`로 고정한 runtime package

OS별 setup script는 가상환경 생성, package 설치, editable project 설치, 기본 설정 검증까지
수행한다. 사용자는 설치 후 OS별 run script로 통합 GUI를 실행한다.

## 전달 단위

전달에 필요한 것은 다음과 같다.

- 같은 Git commit의 저장소 source
- `requirements-lock.txt`
- OS별 setup/run script
- `docs/31_LAB_SOURCE_SETUP.md`
- 별도로 전달하는 device-centric dataset

`.venv`, Conda 환경, 원본 rosbag, 변환 dataset과 작업 라벨은 Git에 포함하지 않는다.

## 재현성

Windows와 Linux CI에서 다음을 반복한다.

1. Python 3.10 clean runner 준비
2. runtime/development lock 설치
3. project editable 설치
4. source 환경 검증
5. Ruff 실행
6. 전체 pytest 실행

실험실 PC에서는 `scripts/verify_source_environment.py`로 Python, package 버전, project import와
기본 설정을 확인한다.

## Linux 시스템 라이브러리

PySide6 wheel만으로 모든 desktop library가 제공되는 것은 아니다. Ubuntu에서는 최소한
`libegl1`, `libgl1`, `libxkbcommon-x11-0`, `libxcb-cursor0`을 준비한다. 실제 3D 렌더링은
GPU/OpenGL driver와 desktop session에 의존하므로 대상 PC에서 GUI smoke test를 수행한다.

## 오프라인 PC

인터넷 연결 PC에서 같은 OS, CPU architecture, Python minor version용 wheelhouse를 만든다.
대상 PC에서는 `--no-index --find-links`로 lock을 설치한다. Windows wheelhouse와 Linux
wheelhouse를 서로 섞지 않는다.

## 데이터와 사용자 파일

- 원본 MCAP/YAML은 변환 source이며 source code와 분리한다.
- 변환 결과 위치는 GUI 또는 CLI에서 사용자가 선택한다.
- 작업 라벨은 dataset sidecar 또는 명시한 workspace에 원자적으로 저장한다.
- 설정과 log는 Windows AppData 또는 Linux XDG 사용자 경로에 둔다.
- source label은 직접 덮어쓰지 않는다.

## 운영 Gate

- setup 종료 시 환경 검증 통과
- Windows/Linux CI 통과
- 대상 dataset preflight 실행
- calibration reference frame과 fingerprint 확인
- nearest sync 반복/점프 QA 확인
- 좌/우 camera projection 확인
- box 저장, 재로드, ID/unknown field 보존 확인
- 한글·공백 경로 확인

자세한 설치 및 업데이트 절차는 `docs/31_LAB_SOURCE_SETUP.md`, 데이터 검수는
`docs/18_PREFLIGHT_AND_QA.md`를 따른다.
