# 통합 EXE 빌드와 배포 매뉴얼

## 1. 사용자 실행

v0.2.0 one-file 배포본은 다음 파일 하나로 실행한다.

```text
LiDARLabelTool_Integrated_<version>.exe
```

Python, `.venv`, PowerShell, BAT, ROS2를 설치하거나 실행하지 않는다. 원본 MCAP/YAML과 변환
dataset은 사용자가 선택하는 외부 폴더에 둔다.

EXE 첫 화면에서 다음 작업을 선택한다.

1. 데이터셋 열기
2. 원본 데이터 변환
3. 기존 데이터 재동기화
4. Calibration JSON 생성
5. Calibration 검증
6. 데이터셋 검사
7. 라벨 통계
8. 라벨 내보내기

최근 source, calibration, output 경로는 다음 사용자 경로에 저장된다.

```text
%LOCALAPPDATA%\LiDARLabelTool\settings.ini
```

## 2. 개발자 빌드

```powershell
.\packaging\build_windows_portable.ps1 `
  -PythonCommand .\.venv\Scripts\python.exe `
  -VenvDirectory .build\windows-portable-venv-py312 `
  -OneFile
```

반복 빌드에서 테스트와 dependency 설치를 이미 별도로 검증했을 때만 다음 옵션을 사용한다.

```powershell
-SkipTests -SkipDependencyInstall
```

산출물:

```text
dist\LiDARLabelTool.exe
```

진단용 one-folder 빌드는 `-OneFile`을 생략한다.

## 3. 릴리스 파일 생성

```powershell
.\packaging\package_windows_onefile_release.ps1 `
  -ReleaseName LiDARLabelTool_Integrated_0.2.0_r1
```

산출물:

```text
release_packages\LiDARLabelTool_Integrated_0.2.0_r1.exe
release_packages\LiDARLabelTool_Integrated_0.2.0_r1.sha256.txt
```

사용자에게 필요한 실행 파일은 EXE 하나다. SHA-256 파일은 전달 무결성 확인과 릴리스 기록에
사용한다.

## 4. 변환 작업

### 전체 변환

- 원본: `calibration/`, `rosbags/`가 있는 루트
- Calibration: intrinsics/extrinsics YAML 네 개가 있는 결과 폴더
- 출력: 아직 존재하지 않는 새 dataset 경로
- 기본 timestamp: `header_aligned`
- 기본 tolerance: 70 ms
- 기본 layout: `simple`

기존 출력 폴더는 자동으로 덮어쓰지 않는다. 변환 중 실패하거나 취소하면 staging 폴더를 정리한다.

### 재동기화

기존 dataset과 원본 rosbags를 선택한다. JPG/BIN은 다시 만들지 않고 `sync/frames.jsonl`만
재생성한다. 기존 파일은 `.bak-<timestamp>-<id>`로 보존한다.

### Calibration 검증

변환 dataset, 원본 YAML 폴더, 검증 결과 폴더를 선택한다. 프레임을 비우면 처음·1/4·중간·3/4·
마지막 대표 프레임을 사용한다. `summary.json`과 camera projection overlay JPG가 생성된다.

## 5. 현장 검수

1. Python이 없는 Windows 10/11 x64 PC에 EXE만 복사한다.
2. 한글과 공백이 있는 경로에서 EXE를 실행한다.
3. 한글과 공백이 있는 source/output 경로로 작은 변환을 실행한다.
4. 변환 완료 후 Preflight 결과를 확인하고 dataset을 연다.
5. point cloud, CAM_LEFT/CAM_RIGHT, frame 진행, projection을 확인한다.
6. 박스를 생성·수정·저장하고 재실행해 값과 ID가 유지되는지 확인한다.
7. 변환 취소 후 부분 dataset이 정상 dataset처럼 남지 않는지 확인한다.
8. 재동기화 전 파일 백업과 camera 반복/점프 QA를 확인한다.
9. Calibration overlay를 육안으로 승인한다.
10. Defender, SmartScreen, OpenGL, 원격 데스크톱 결과를 기록한다.

## 6. 알려진 제한

- one-file은 실행 시 내부 파일을 임시 폴더에 풀기 때문에 one-folder보다 시작이 느릴 수 있다.
- 현재 내장 MCAP reader는 압축 chunk를 지원하지 않는다.
- 코드 서명이 없으면 SmartScreen 경고가 표시될 수 있다.
- 프로젝트 자체 라이선스가 아직 선언되지 않아 공개 재배포 전에 결정해야 한다.
