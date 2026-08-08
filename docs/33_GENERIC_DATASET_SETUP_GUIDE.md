# 범용 데이터셋 v2 구성·사용 가이드

이 가이드는 ROS bag/MCAP 변환기가 아니라, 이미 파일로 정리된 LiDAR와 선택적 카메라를
LiDAR Label Tool에서 바로 구성하고 라벨링하는 절차다. `dataset.json`, taxonomy, frame index는
프로그램이 생성하므로 사용자가 JSON을 직접 작성하지 않는다.

## 0. 실행 준비

현재 프로그램은 Python이 포함된 EXE가 아니라 source 가상환경으로 실행한다. 새 Windows PC에는
python.org 공식 Python 3.12 64-bit와 Git을 먼저 설치하고, 현재 `codex/v2` 브랜치에서 다음을
한 번 실행한다.

```powershell
.\launchers\windows\setup_windows.bat
.\launchers\windows\run_windows.bat
```

Conda Python만으로 Windows `.venv`를 만들지 않는다. 설치와 Qt DLL 복구 절차는 루트
`README.md`와 `docs/31_LAB_SOURCE_SETUP.md`를 따른다.

## 1. 준비할 원본

### LiDAR

- 선택 가능한 형식: `.bin`, `.pcd`
- 센서별 파일은 서로 다른 폴더에 둔다.
- 한 profile은 LiDAR 하나만 사용한다. 여러 LiDAR 폴더를 선택하면 센서별 독립 profile을 만든다.
- LiDAR를 자동 병합하지 않는다.
- BIN은 dense `float32` 배열이어야 하며 열 순서를 화면에서 직접 입력한다.
- 모든 LiDAR에는 `x`, `y`, `z` 열이 필요하다.
- PCD는 ASCII 또는 uncompressed binary v0.7을 지원한다. `binary_compressed`는 지원하지 않는다.

예:

```text
my_data/
├─ lidar/
│  ├─ AEVA/
│  │  ├─ 000000.bin
│  │  └─ 000001.bin
│  └─ LIDAR_POINTS/
│     ├─ 000000.bin
│     └─ 000001.bin
```

### 카메라

- 선택 가능한 형식: `.jpg`, `.jpeg`, `.png`
- 한 구성에는 카메라를 0개 또는 1개만 선택한다.
- 카메라가 없거나 이미지 일부가 누락되어도 정상 LiDAR frame은 그대로 라벨링한다.
- 이미 좌·우 영상이 합성/보정된 파일은 논리 카메라 한 개로 선택할 수 있다. 합성되었다는 이유만으로
  3D projection calibration이 있다고 간주하지 않는다.

### Timestamp

다음 셋 중 하나를 고른다.

1. `LiDAR만 사용`: timestamp 파일이 필요 없다.
2. `같은 파일 stem`: LiDAR와 이미지의 stem이 같을 때 연결한다.
3. `가장 가까운 timestamp`: LiDAR와 카메라 각각의 CSV가 필요하다.

nearest CSV는 UTF-8 또는 UTF-8 BOM을 지원하며, 화면에서 다음을 명시한다.

- sample ID 컬럼: CSV 행을 point/image 파일의 원본 stem과 연결하는 열
- 정수 timestamp 컬럼: CSV에 시간이 여러 개 있을 때 실제 동기화에 사용할 열
- 단위: 선택한 숫자가 `ns`, `us`, `ms`, `s` 중 무엇인지 선언
- clock domain: `bag`, `header`, `device`처럼 같은 시간 기준인지 구분하는 identity
- 허용 오차

clock domain은 단위 변환이나 자동 시간 보정값이 아니다. 두 센서의 clock domain이 다르면
연결하지 않는다. 내부 계산은 정수 nanosecond를 유지한다. `metadata/<SENSOR_ID>.json`에
`point_columns`가 명시된 입력은 그 전체 열 순서를 화면에 자동 입력하지만, 좌표계는 사용자가
계속 명시적으로 확인해야 한다.

```csv
sample_id,timestamp_ns
000000,1778225784354747202
000001,1778225784454747202
```

## 2. 프로그램에서 처음 구성하기

1. `launchers/windows/run_windows.bat` 또는 `launchers/linux/run_linux.sh`를 실행한다.
2. `데이터 폴더/데이터셋 열기`를 누른다.
3. `dataset.json`이 없는 원본 폴더를 선택한다.
4. 자동 탐색 결과에서 사용할 LiDAR를 하나 이상 체크한다.
5. 각 LiDAR의 point columns를 직접 입력한다. 예: `x,y,z,intensity`.
6. 좌표 계약 `meter / x-forward / y-left / z-up / +z yaw`를 확인한다.
7. 카메라는 없음 또는 하나를 선택한다.
8. sync 방식과 필요한 CSV 컬럼·단위·clock·tolerance를 입력한다.
9. 원본이 읽기 전용이면 `구성/라벨 폴더`를 별도 쓰기 가능한 위치로 바꾼다.
10. `구성 분석`을 눌러 profile별 LiDAR frame 수, 카메라 match/unmatched, reuse와 최대
    timestamp 차이를 확인한다. 이 단계에서는 파일을 생성하지 않는다.
11. 결과가 맞으면 `검증 결과로 생성`을 누른다. 분석 뒤 설정이나 원본 파일이 바뀌면 다시
    분석해야 한다.

프로그램은 대표 LiDAR payload, timestamp, schema와 전체 frame binding을 검사한 후에만
`dataset.json`을 마지막 단계에서 활성화한다. 중간에 실패하거나 취소하면 미완성 generation을
제거하고 원본 파일은 그대로 둔다.

## 3. 생성되는 파일

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

`*.frames.jsonl`은 프로그램이 확정한 LiDAR frame 순서와 선택적 카메라 연결표다. 사용자가
센서별 JSONL을 미리 만들 필요가 없다. `dataset.json`은 현재 활성 generation을 가리키는 commit
pointer 역할을 한다.

## 4. 여러 LiDAR를 라벨링하기

데이터셋을 열 때 profile 선택 창에서 이번 세션의 LiDAR 하나를 선택한다. 다른 LiDAR는 별도
세션/profile로 연다. 동일한 `frame_id`라도 라벨 경로가
`<profile_id>/<label_lidar_id>/<frame_id>.json`으로 분리되므로 서로 덮어쓰지 않는다.

한 세션에서 여러 LiDAR를 합치거나 동시에 활성화하지 않는다. 각 profile의 LiDAR 좌표계가 그
profile 라벨의 reference frame이다.

### 이미 생성한 데이터셋에 LiDAR profile 추가

초기 구성에서 LiDAR 하나만 등록했더라도 데이터셋을 삭제하거나 새 dataset ID를 만들 필요가 없다.

1. 첫 화면에서 `범용 v2 LiDAR profile 추가`를 누른다.
2. 기존 `dataset.json`이 있는 구성 폴더를 선택한다.
3. 미등록 LiDAR, metadata의 전체 point columns, timestamp CSV와 clock 설정을 확인한다.
4. 좌표 계약을 확인하고 `변경 분석`을 누른다.
5. frame/match/unmatched/reuse/max delta와 보존할 기존 라벨 수를 확인한다.
6. `새 profile 추가`를 누른다.

프로그램은 기존 dataset ID, 기본 profile, 라벨과 이전 generation을 유지한다. 기존 index와 taxonomy,
새 profile index를 다음 revision의 한 generation에 기록하고 `dataset.json`을 마지막에 원자적으로
교체한다. 분석 후 원본이나 manifest가 바뀌거나 저장이 실패하면 추가를 거부하고 기존 구성을
그대로 연다. 완료 후 새 profile로 바로 라벨링 화면을 연다.

## 5. Timestamp를 다시 연결하기

첫 화면의 `범용 v2 재동기화`를 사용한다.

1. 구성 폴더를 선택한다.
2. profile, 방식, tolerance를 고른다.
3. `변경 분석`을 눌러 profile별 match/unmatched, camera binding 변경, frame 순서 변경을 확인한다.
4. `새 generation 적용`을 누른다.

재동기화는 모든 profile의 index를 같은 새 generation에 기록한다. LiDAR frame/sample/path binding은
변경할 수 없고, 기존 generation과 profile별 라벨은 보존한다. 분석 후 manifest나 원본 입력이
바뀌면 적용을 거부하고 다시 분석하도록 안내한다.

CLI에서도 같은 논리 transaction을 사용할 수 있다.

```powershell
.\.venv\Scripts\python.exe -m lidar_label_tool validate-v2 C:\data\dataset_config
.\.venv\Scripts\python.exe -m lidar_label_tool resync-v2 C:\data\dataset_config `
  --profile aeva_profile --method timestamp_nearest --tolerance-ms 50
```

## 6. Calibration

Calibration은 선택 사항이다. 없거나 손상된 경우 카메라는 display-only로 유지되고 LiDAR 라벨링과
저장은 계속된다. calibrated profile은 활성 LiDAR coordinate frame과 같은 `reference_frame`, 해당
camera ID, 유효한 rigid transform과 image size를 가져야 한다. 불일치하면 projection만 끈다.

별도 도구로 calibration을 조정할 때도 원본을 덮어쓰지 않고 조정본을 따로 저장한다. 새 조정본을
활성 구성에 연결하는 작업은 manifest identity와 기존 라벨을 검수하는 명시적 구성 변경 절차로
처리해야 한다.

## 7. one_chip 레거시 기능과의 구분

`one_chip MCAP/ROS bag 변환`, 기존 one_chip 재동기화, YAML 변환·검증은 특정 취득 구조를 위한
호환 기능이다. 첫 화면의 `고급 도구 — one_chip 레거시 전용`에 보존되어 있으며 범용 데이터 폴더
구성에는 사용하지 않는다.
