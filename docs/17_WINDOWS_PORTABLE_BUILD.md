# Windows 포터블 빌드

## 목적

Python이 설치되지 않은 Windows PC에서 `LiDARLabelTool.exe`를 실행할 수 있는 PyInstaller
one-folder 배포본을 만든다. 데이터셋, 작업 라벨, 사용자 설정과 로그는 실행 파일에 포함하지
않는다.

## 사전 조건

- Windows 10/11 64-bit
- Python 3.10 이상 또는 Windows Python Launcher(`py`)
- 인터넷 연결: 최초 의존성 설치 시 필요
- PowerShell 5.1 이상
- 빌드와 테스트를 위한 충분한 디스크 공간

## 빌드

저장소 루트의 PowerShell에서 실행한다.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\packaging\build_windows_portable.ps1
```

스크립트는 다음 작업을 순서대로 수행한다.

1. `.build\windows-portable-venv` 가상환경 생성 또는 재사용
2. GUI, 검증, 개발, PyInstaller 의존성 설치
3. `python -m pytest`와 `python -m ruff check .` 실행
4. `dist\LiDARLabelTool\` one-folder 배포본 생성

`py` 대신 특정 Python 실행 파일을 사용하려면 다음처럼 지정한다.

```powershell
.\packaging\build_windows_portable.ps1 -PythonCommand "C:\Python310\python.exe"
```

반복 빌드 중 테스트를 별도로 완료한 경우에만 `-SkipTests`를 사용할 수 있다.

## 결과물과 실행

실행 파일은 다음 위치에 생성된다.

```text
dist\LiDARLabelTool\LiDARLabelTool.exe
```

`LiDARLabelTool` 폴더 전체가 배포 단위다. EXE 하나만 복사하면 Qt/OpenGL 런타임이 누락되어
실행되지 않는다. 실행하면 데이터셋 폴더 선택 창이 열린다.

## 깨끗한 PC 검증 절차

1. Python과 개발 도구가 설치되지 않은 Windows 10/11 64-bit PC 또는 VM을 준비한다.
2. `dist\LiDARLabelTool` 폴더 전체를 한글과 공백이 포함된 경로에 복사한다.
3. `LiDARLabelTool.exe`를 실행한다.
4. 한글과 공백이 포함된 별도 경로의 작은 검증 데이터셋을 연다.
5. 포인트 클라우드와 카메라 이미지 표시, 객체 선택, BEV/측면 편집을 확인한다.
6. 라벨 저장 후 JSON을 다시 열어 ID, class, box 값과 revision이 유지되는지 확인한다.
7. 앱을 두 번 실행해 동일 데이터셋 세션 잠금 경고가 표시되는지 확인한다.
8. 저장하지 않은 편집 후 프로세스를 강제 종료하고 재실행해 복구 선택 창을 확인한다.

## 샘플 데이터 정책

대용량 또는 사용자 제공 데이터는 배포본에 포함하지 않는다. 공개 가능한 최소 샘플이 필요하면
별도 ZIP으로 제공하고 라이선스, 좌표계, 보정 파일 출처를 함께 기록한다. PyInstaller 입력에
`local_data/`, `dataset/`, `datasets/`를 추가하지 않는다.

## 알려진 제한과 위험

- 현재 배포본은 코드 서명이 없으므로 Windows SmartScreen 경고가 표시될 수 있다.
- OpenGL 드라이버가 없거나 원격 데스크톱의 가속이 제한되면 3D 표시가 실패할 수 있다.
- PyInstaller 빌드는 빌드한 Windows 아키텍처와 같은 아키텍처에서 사용해야 한다.
- GUI 전용 EXE에는 콘솔 CLI가 포함되지 않는다. CLI가 필요하면 소스 설치 후
  `lidar-label-tool` 명령을 사용한다.
- 최종 배포 전 third-party license 목록과 바이러스 검사 결과를 릴리스 기록에 남겨야 한다.
