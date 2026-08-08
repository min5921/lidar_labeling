# 통합 데스크톱 워크플로 v0.3.0

## 1. 목표

Windows/Linux 소스 가상환경에서 실행한 통합 GUI 하나로 다음 사용자 작업을 수행한다.
범용 데이터 구성에는 ROS2나 별도 MCAP 도구가 필요하지 않는다.

- 기존 v1/v2/Waymo dataset 열기
- JSON이 없는 BIN/PCD 원본 폴더를 범용 v2 dataset으로 구성
- 여러 LiDAR 후보를 독립 profile로 등록하고 profile당 하나만 라벨링
- camera 0~1개와 exact/timestamp-nearest frame index generation 생성
- 기존 v2 dataset에 새 LiDAR profile 추가
- point/image 원본을 유지하고 v2 frame index generation만 안전하게 재동기화
- dataset preflight와 label 통계 확인
- 비파괴 LiDAR–camera calibration 편집
- 작업 라벨을 명시적으로 export

특정 one_chip 형식 MCAP 변환, 기존 `sync/frames.jsonl` 재생성, calibration YAML 변환·검증은
접힌 레거시 영역에서 계속 지원한다.

가상환경 설치와 dependency 업데이트는 setup/개발 작업이므로 실행 중인 GUI에 넣지 않는다.

## 2. 배포와 데이터 경계

- 실험실 운영본은 Windows/Linux source 가상환경 실행을 기본으로 한다.
- 원본 MCAP, calibration YAML, 변환 dataset, 작업 라벨, export 결과는 저장소 밖에 둔다.
- 사용자가 source, calibration, output, workspace, export 경로를 직접 선택한다.
- Windows 최근 경로와 사용자 설정은 `%LOCALAPPDATA%\LiDARLabelTool\` 아래에 저장한다.
- Linux 설정은 XDG config, log는 XDG state, 사용자 데이터는 XDG data 경로에 저장한다.
- 설정과 작업 log는 저장소가 아니라 사용자 쓰기 가능 경로에 둔다.

## 3. 서비스 경계

GUI와 CLI는 같은 비-Qt 서비스를 호출한다.

```text
GUI / CLI
  -> DatasetDiscovery / DatasetSetupService
  -> DatasetProfileAdd / DatasetResyncV2
  -> DatasetPreflight
  -> LabelStatistics
  -> CalibrationEditor / CalibrationRepository
  -> ExporterRegistry
  -> OneChipConversionService (legacy)
```

- 서비스는 PowerShell 또는 BAT를 호출하지 않는다.
- 변환 서비스는 Qt/OpenGL 객체를 사용하지 않는다.
- UI는 manifest, timestamp CSV, MCAP/CDR/YAML 또는 frame-index 구조를 직접 파싱·저장하지 않는다.
- 긴 작업은 worker에서 실행하며 진행률, 취소 요청, 구조화된 결과를 제공한다.

## 4. 범용 v2 구성 모드

### 신규 구성

- `dataset.json`이 없는 원본에서 BIN/PCD, image와 timestamp CSV 후보를 탐색한다.
- BIN의 전체 point columns, coordinate frame, timestamp column/unit/clock domain을 사용자가
  명시적으로 확인한다.
- 선택한 LiDAR마다 독립 profile을 만들고 한 profile에는 camera를 최대 하나만 둔다.
- 분석 단계는 frame/match/unmatched/reuse/max delta를 표시하지만 파일을 쓰지 않는다.
- schema·payload·preflight를 통과한 generation을 먼저 완성하고 `dataset.json`을 마지막에
  원자적으로 활성화한다.
- 실패·취소·fingerprint 충돌은 기존 manifest/index/label과 source를 그대로 보존한다.

### Profile 추가와 재동기화

- 기존 v2에 미등록 LiDAR를 추가해도 dataset ID와 기존 profile/label을 유지한다.
- 재동기화는 LiDAR frame/sample/path binding을 바꾸지 않고 camera 연결만 새 generation으로
  갱신한다.
- 모든 profile index와 taxonomy는 한 generation에 함께 기록해 서로 다른 세대가 섞이지 않게 한다.

## 5. one_chip 레거시 변환 모드

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

## 6. 통합 시작 화면

첫 화면은 작업 선택기이며 다음 명령을 제공한다.

- `데이터 폴더/데이터셋 열기`
- `범용 v2 재동기화`
- `범용 v2 LiDAR profile 추가`
- `데이터셋 검사`
- `라벨 통계`
- `라벨 내보내기`
- `정보`

`고급 도구 — one_chip 레거시 전용`을 펼치면 다음 명령을 제공한다.

- `one_chip MCAP/ROS bag 변환`
- `one_chip 기존 결과 재동기화`
- `one_chip Calibration JSON 생성`
- `one_chip Calibration 검증`

변환 화면은 source, calibration, output, dataset ID, bag 선택, timestamp source, tolerance,
camera frame convention, image mode를 편집할 수 있어야 한다. 경로를 코드에 하드코딩하지 않는다.

## 7. 오류와 취소

- 사용자 메시지는 작업 단계와 복구 방법을 한국어로 표시한다.
- 개발자 log에는 예외 종류, 입력 경로, 작업 모드, 설정, traceback을 기록한다.
- 취소는 현재 파일 단위 작업을 마친 뒤 반영할 수 있으나 UI는 즉시 취소 요청 상태를 표시한다.
- 취소 후 부분 output을 정상 dataset처럼 노출하지 않는다.
- 디스크 공간, 쓰기 권한, 필수 파일, MCAP 압축 방식과 토픽을 쓰기 전에 검사한다.
- 현재 내장 MCAP reader가 지원하지 않는 압축 chunk는 변환 전에 명시적으로 거부한다.

## 8. 박스 출력 계약

저장·export 박스 값은 기존 계약을 유지한다.

```text
[x, y, z, length, width, height, yaw]
```

- x/y/z는 dataset reference frame의 박스 기하 중심이며 단위는 meter다.
- length/width/height는 local x/y/z 방향 크기이며 0보다 커야 한다.
- JSON yaw는 +z축 radian이고 `[-pi, pi)`로 정규화한다.
- UI에서만 yaw를 degree로 표시한다.
- source label 저장, working save, 명시적 export는 서로 분리한다.

## 9. 내부 운영 Gate

- `pytest`, `ruff check .`, `git diff --check` 통과
- Windows/Linux 고정 가상환경 설치 성공
- source 환경 검증, Ruff, pytest 성공
- 동일 commit과 dependency lock 기록
- 범용 v2 LiDAR 1/2+, camera 0/1, exact/nearest, calibration 없음/유효/손상 조합 통과
- profile별 같은 frame ID label namespace 충돌 없음
- sync 실패·camera 누락에도 LiDAR frame 수와 순서 보존
- 실제 `one_chip_converted` preflight와 calibration verification 통과
- 공식 Python 3.12 x64 Windows와 Python 3.10+ Linux 실험실 PC에서 setup 후 실행
- 한글·공백 경로에서 source 선택, 변환, dataset open, edit, save, reload 성공
- 취소·실패 후 기존 v2 generation/dataset/label과 legacy `frames.jsonl` 보존
- Windows/Linux OpenGL과 원격 데스크톱 결과 기록
