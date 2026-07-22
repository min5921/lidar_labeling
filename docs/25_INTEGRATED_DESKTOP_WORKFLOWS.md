# 통합 데스크톱 워크플로 v0.2.0

## 1. 목표

`LiDARLabelTool.exe` 하나에서 다음 사용자 작업을 수행한다. 사용자는 PowerShell, BAT, Python,
ROS2를 직접 실행하거나 설치하지 않는다.

- 변환된 device-centric dataset 열기
- one_chip 형식 MCAP와 calibration YAML을 새 dataset으로 변환
- 기존 dataset의 `sync/frames.jsonl`만 안전하게 재생성
- calibration YAML을 `calibration.json`으로 변환
- dataset preflight와 label 통계 확인
- calibration 구조·원본 YAML 대조·projection overlay 검증
- 작업 라벨을 명시적으로 export

앱 빌드, 릴리스 ZIP 생성, 코드 서명은 개발자 작업이므로 실행 중인 제품 EXE에 넣지 않는다.

## 2. 배포와 데이터 경계

- 사용자 배포본은 PyInstaller one-file `LiDARLabelTool.exe`를 기본으로 한다.
- 장애 분석용 one-folder 빌드도 같은 소스와 버전으로 생성한다.
- 원본 MCAP, calibration YAML, 변환 dataset, 작업 라벨, export 결과는 EXE 밖에 둔다.
- 사용자가 source, calibration, output, workspace, export 경로를 직접 선택한다.
- Windows 최근 경로와 사용자 설정은 `%LOCALAPPDATA%\LiDARLabelTool\` 아래에 저장한다.
- Linux 설정은 XDG config, log는 XDG state, 사용자 데이터는 XDG data 경로에 저장한다.
- crash log와 작업 log는 번들 또는 EXE 옆에 쓰지 않는다.

## 3. 서비스 경계

GUI와 CLI는 같은 비-Qt 서비스를 호출한다.

```text
GUI / CLI
  -> OneChipConversionService
  -> DatasetPreflight
  -> LabelStatistics
  -> CalibrationVerificationService
  -> ExporterRegistry
```

- 서비스는 PowerShell 또는 BAT를 호출하지 않는다.
- 변환 서비스는 Qt/OpenGL 객체를 사용하지 않는다.
- UI는 MCAP, CDR, YAML, `frames.jsonl` 구조를 직접 파싱하지 않는다.
- 긴 작업은 worker에서 실행하며 진행률, 취소 요청, 구조화된 결과를 제공한다.

## 4. 변환 모드

### 전체 변환

- source root 아래 `calibration/`과 `rosbags/`를 사전 검사한다.
- output이 이미 있으면 자동 덮어쓰지 않는다.
- output 옆 staging 폴더에서 작업한 뒤 성공 시 한 번에 이름을 바꾼다.
- 실패 또는 취소 시 staging 폴더를 정리하고 기존 output을 보존한다.
- 기본 timestamp는 `header_aligned`, tolerance는 70 ms다.
- 기본 물리 구조는 `lidar/`, `cam_left/`, `cam_right/`인 `simple` layout이다.

### 재동기화

- BIN/JPG는 다시 생성하지 않는다.
- 기존 `sync/frames.jsonl`을 고유한 `.bak-<timestamp>-<id>`로 백업한다.
- 새 파일은 임시 파일로 쓴 뒤 원자적으로 교체한다.
- camera sample 반복, 건너뜀, 최대 반복 길이와 timestamp 간격 QA를 결과 화면에 표시한다.

### Calibration 변환·검증

필수 입력:

- `cam_left_intrinsics.yaml`
- `cam_right_intrinsics.yaml`
- `cam_left_lidar_extrinsics.yaml`
- `cam_right_lidar_extrinsics.yaml`

검증 항목:

- intrinsic shape, 양수 focal length, image size
- distortion model과 coefficient
- `T_camera_reference` shape와 finite 값
- 회전행렬 determinant와 orthogonality
- `MERGED.T_reference_sensor` identity
- 원본 YAML 재생성 결과와 현재 JSON 비교
- 대표 frame LiDAR projection overlay 육안 확인

구조 검사가 통과해도 overlay가 맞지 않으면 calibration을 승인하지 않는다.

## 5. 통합 시작 화면

첫 화면은 작업 선택기이며 다음 명령을 제공한다.

- `데이터셋 열기`
- `원본 데이터 변환`
- `기존 데이터 재동기화`
- `Calibration 변환/검증`
- `데이터셋 검사`
- `라벨 통계`
- `라벨 내보내기`

변환 화면은 source, calibration, output, dataset ID, bag 선택, timestamp source, tolerance,
camera frame convention, image mode를 편집할 수 있어야 한다. 경로를 코드에 하드코딩하지 않는다.

## 6. 오류와 취소

- 사용자 메시지는 작업 단계와 복구 방법을 한국어로 표시한다.
- 개발자 log에는 예외 종류, 입력 경로, 작업 모드, 설정, traceback을 기록한다.
- 취소는 현재 파일 단위 작업을 마친 뒤 반영할 수 있으나 UI는 즉시 취소 요청 상태를 표시한다.
- 취소 후 부분 output을 정상 dataset처럼 노출하지 않는다.
- 디스크 공간, 쓰기 권한, 필수 파일, MCAP 압축 방식과 토픽을 쓰기 전에 검사한다.
- 현재 내장 MCAP reader가 지원하지 않는 압축 chunk는 변환 전에 명시적으로 거부한다.

## 7. 박스 출력 계약

저장·export 박스 값은 기존 계약을 유지한다.

```text
[x, y, z, length, width, height, yaw]
```

- x/y/z는 dataset reference frame의 박스 기하 중심이며 단위는 meter다.
- length/width/height는 local x/y/z 방향 크기이며 0보다 커야 한다.
- JSON yaw는 +z축 radian이고 `[-pi, pi)`로 정규화한다.
- UI에서만 yaw를 degree로 표시한다.
- source label 저장, working save, 명시적 export는 서로 분리한다.

## 8. 릴리스 Gate

- `pytest`, `ruff check .`, `git diff --check` 통과
- one-file과 one-folder 빌드 성공
- EXE 버전 정보, 제품명, 파일 설명과 앱 아이콘 포함
- third-party license 목록 포함
- release ZIP/EXE SHA-256 기록
- 실제 `one_chip_converted` preflight와 calibration verification 통과
- Python 미설치 Windows 10/11 x64에서 실행
- 한글·공백 경로에서 source 선택, 변환, dataset open, edit, save, reload 성공
- 취소·실패 후 기존 dataset과 `frames.jsonl` 보존
- Windows Defender/SmartScreen, OpenGL, 원격 데스크톱 결과 기록

코드 서명이 없으면 배포 기록에 명시하고 SmartScreen 경고 가능성을 사용자에게 안내한다.
