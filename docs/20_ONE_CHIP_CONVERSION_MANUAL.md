# one_chip 데이터 변환 및 실행 매뉴얼

이 문서는 `E:\one_chip` 실제 취득 데이터를 LiDAR Label Tool에서 열 수 있는
device-centric dataset으로 변환하고 검수·실행하는 절차를 정리한다.

## 1. 이번 작업으로 만든 결과

변환 결과는 다음 위치에 생성했다.

```text
E:\one_chip_converted
```

현재 이미 만들어진 `E:\one_chip_converted`는 다음 legacy 구조일 수 있다.

```text
one_chip_converted/
├─ dataset.json
├─ conversion_report.json
├─ calibration/
│  └─ calibration.json
├─ sensors/
│  ├─ lidar/MERGED/frames/*.bin
│  └─ camera/
│     ├─ CAM_LEFT/images/*.jpg
│     └─ CAM_RIGHT/images/*.jpg
└─ sync/
   └─ frames.jsonl
```

앞으로 `scripts/convert_one_chip_dataset.py`로 새로 변환하는 기본 구조는 더 단순하다.

```text
one_chip_converted/
├─ dataset.json
├─ conversion_report.json
├─ calibration/
│  └─ calibration.json
├─ lidar/*.bin
├─ cam_left/*.jpg
├─ cam_right/*.jpg
└─ sync/
   └─ frames.jsonl
```

`MERGED`, `CAM_LEFT`, `CAM_RIGHT`는 실제 폴더명이 아니라 `dataset.json` 안의 논리 sensor ID다.
GUI는 `dataset.json`의 `data_patterns`를 보고 위 단순 폴더에서 파일을 찾는다.

현재 변환 요약:

| 항목 | 값 |
|---|---:|
| logical frame | 3754 |
| MERGED LiDAR BIN | 3754 |
| CAM_LEFT JPG | 3776 |
| CAM_RIGHT JPG | 3774 |
| sync 기준 | MCAP header timestamp, first log time aligned |
| nearest sync tolerance | 70 ms |
| CAM_LEFT 최대 sync delta | 43.862931 ms |
| CAM_RIGHT 최대 sync delta | 56.268995 ms |
| preflight error | 0 |
| preflight warning | 0 |

원본 LiDAR label은 없으므로 GUI에서는 빈 라벨부터 시작한다. 새 박스를 만든 뒤
CAM_LEFT/CAM_RIGHT live projection으로 calibration을 확인한다.

## 2. 추가된 실행 묶음

사용자가 바로 실행할 수 있도록 다음 폴더를 추가했다. 이 폴더는 repo에 남는 원본 실행 묶음이다.

```text
packaging/one_chip_run_pack/
```

같은 내용의 압축본도 함께 만들었다. `artifacts/`는 생성물 폴더라 git에는 넣지 않는다.

```text
artifacts/one_chip_run_pack.zip
```

포함 파일:

| 파일 | 용도 |
|---|---|
| `00_preflight_one_chip.bat` | `E:\one_chip_converted` dataset 사전검수 |
| `01_open_one_chip_gui.bat` | 변환된 dataset을 GUI로 열기 |
| `02_convert_one_chip_full.bat` | `E:\one_chip` 원본에서 전체 dataset 재변환 |
| `03_resync_one_chip_70ms.bat` | 기존 변환 결과의 `sync/frames.jsonl`만 70 ms 기준으로 재생성 |
| `04_stats_one_chip.bat` | source label 통계 확인 |
| `05_write_calibration_json_only.bat` | calibration YAML만 `calibration.json`으로 변환 |
| `07_verify_calibration.bat` | 원본 YAML과 변환 JSON 대조 및 projection overlay 생성 |

각 `.bat`는 저장소 루트를 자동으로 찾아 실행하고, 기본 경로는 변환 스크립트 맨 위의 설정값을
읽어서 사용한다. 필요하면 첫 번째 인자로 다른 dataset/output 경로를 한 번만 넘길 수도 있다.

## 3. 가장 자주 쓰는 순서

### 3.0 경로와 export 위치 바꾸기

다른 취득 데이터나 다른 export 위치를 쓰려면 아래 파일 맨 위의 `User-editable defaults` 블록만
수정한다.

```text
scripts/convert_one_chip_dataset.py
```

주로 바꿀 값:

```python
DEFAULT_SOURCE_ROOT = Path(r"E:\one_chip")
DEFAULT_CALIBRATION_ROOT = (
    DEFAULT_SOURCE_ROOT / "calibration" / "results" / "apriltag_calib_main_02"
)
DEFAULT_OUTPUT_ROOT = Path(r"E:\one_chip_converted")
DEFAULT_CALIBRATION_JSON_OUTPUT = Path("artifacts/one_chip_calibration_preview.json")

DEFAULT_DATASET_ID = "one_chip_20260708"
DEFAULT_SYNC_TOLERANCE_MS = 70.0
DEFAULT_TIMESTAMP_SOURCE = "header_aligned"
DEFAULT_DATASET_LAYOUT = "simple"
```

의미:

| 설정 | 의미 |
|---|---|
| `DEFAULT_SOURCE_ROOT` | 원본 `calibration/`, `rosbags/`가 들어 있는 루트 |
| `DEFAULT_CALIBRATION_ROOT` | calibration YAML 폴더 |
| `DEFAULT_OUTPUT_ROOT` | 변환된 GUI용 dataset 생성 위치 |
| `DEFAULT_CALIBRATION_JSON_OUTPUT` | calibration JSON만 따로 만들 때의 출력 위치 |
| `DEFAULT_DATASET_ID` | 작업 라벨 namespace에 쓰이는 dataset ID |
| `DEFAULT_SYNC_TOLERANCE_MS` | LiDAR-camera nearest sync 허용 범위 |
| `DEFAULT_TIMESTAMP_SOURCE` | sync timestamp 기준. 현재 데이터는 `header_aligned` 권장 |
| `DEFAULT_DATASET_LAYOUT` | 출력 폴더 구조. 기본 `simple`, 예전 구조는 `legacy` |

이 값을 바꾼 뒤에는 `.bat` 파일을 수정하지 않아도 된다. `00_preflight`, `01_gui`, `02_convert`,
`03_resync`, `05_calibration_only`가 모두 이 기본값을 읽는다.

### 3.1 이미 변환된 dataset 열기

저장소 루트에서 실행:

```powershell
.\packaging\one_chip_run_pack\00_preflight_one_chip.bat
.\packaging\one_chip_run_pack\07_verify_calibration.bat
.\packaging\one_chip_run_pack\01_open_one_chip_gui.bat
```

직접 명령으로 실행하려면:

```powershell
.\.venv\Scripts\lidar-label-tool.exe preflight <DEFAULT_OUTPUT_ROOT>
.\.venv\Scripts\lidar-label-tool.exe gui <DEFAULT_OUTPUT_ROOT>
```

preflight 기대 결과:

```text
Frames: 3754 (usable: 3754)
LiDARs: MERGED
Cameras: CAM_LEFT, CAM_RIGHT
Issues: errors=0, warnings=0, info=1
```

`source_labels_absent` info는 원본 라벨이 없다는 뜻이며 정상이다.

calibration 검증 결과는 다음 위치에 저장된다.

```text
artifacts/calibration_verify/summary.json
artifacts/calibration_verify/frame_<frame_id>_<camera>_projection.jpg
```

### 3.2 원본에서 전체 재변환

기존 `E:\one_chip_converted`가 있으면 변환기는 덮어쓰지 않고 중단한다.
재생성이 필요하면 기존 폴더를 직접 rename하거나 백업한 뒤 실행한다.

```powershell
.\packaging\one_chip_run_pack\02_convert_one_chip_full.bat
```

직접 명령:

```powershell
.\.venv\Scripts\python.exe scripts\convert_one_chip_dataset.py
```

명령줄 옵션을 생략하면 `User-editable defaults` 블록의 경로와 설정을 사용한다.
새 기본 출력은 `lidar/`, `cam_left/`, `cam_right/` 단순 구조다. 예전 `sensors/lidar/MERGED/frames`
구조가 꼭 필요하면 다음처럼 실행한다.

```powershell
.\.venv\Scripts\python.exe scripts\convert_one_chip_dataset.py --dataset-layout legacy
```

전체 변환은 큰 MCAP 파일을 순차로 읽고 JPG/BIN을 쓰므로 시간이 걸린다.

### 3.3 sync tolerance만 다시 조정

이미 BIN/JPG 변환이 끝난 상태에서 `frames.jsonl`만 다시 만들 때 사용한다.
이미지와 포인트 파일은 다시 쓰지 않는다.

```powershell
.\packaging\one_chip_run_pack\03_resync_one_chip_70ms.bat
```

직접 명령:

```powershell
.\.venv\Scripts\python.exe scripts\convert_one_chip_dataset.py --sync-only-existing
```

`sync-only-existing`은 기존 `sync/frames.jsonl`을 먼저 다음 형태로 백업한 뒤 새 파일로 교체한다.

```text
sync/frames.jsonl.bak-<UTC timestamp>-<id>
```

처음에는 `log` timestamp 기준으로 변환했지만 일부 구간에서 LiDAR log 간격이 1 ms, 0.9 ms,
52 ms, 835 ms처럼 튀어 camera sample이 반복되는 문제가 있었다. raw `header`만 쓰면 LiDAR와
camera header clock의 epoch가 서로 달라 tolerance 밖으로 빠진다. 현재 기본값인 `header_aligned`는
각 stream의 header 간격을 유지하면서 첫 MCAP log time에 clock offset만 맞춘다.

## 4. Calibration 변환 규칙

입력 YAML:

```text
E:\one_chip\calibration\results\apriltag_calib_main_02
```

사용 파일:

```text
cam_left_intrinsics.yaml
cam_right_intrinsics.yaml
cam_left_lidar_extrinsics.yaml
cam_right_lidar_extrinsics.yaml
```

원본 extrinsic 방향:

```text
p_cam_left  = R_lidar_to_cam_left  * p_lidar + t_lidar_to_cam_left
p_cam_right = R_lidar_to_cam_right * p_lidar + t_lidar_to_cam_right
```

`calibration/calibration.json`에서는:

- `reference_frame`: `robosense`
- `lidars.MERGED.T_reference_sensor`: identity
- `CAM_LEFT`, `CAM_RIGHT`의 `T_camera_reference`: LiDAR/reference에서 camera로 가는 transform
- `plumb_bob`: `brown_conrady`
- `distortion_coefficients`: `[k1, k2, p1, p2, k3]`

주의: 원본 YAML의 camera 좌표는 ROS/OpenCV optical frame이다. 현재 GUI projection 코드는
tool camera frame을 기대하므로 변환 스크립트의 기본값은 optical 축을 tool camera 축으로 바꿔
`T_camera_reference`를 저장한다. 이 사실은 `calibration.json`의 `metadata`에 기록된다.

raw YAML transform을 그대로 쓰고 싶으면 다음 옵션을 사용한다.

```powershell
--camera-frame-convention as_provided
```

### 4.1 Calibration 재검증

변환 후 calibration만 다시 확인하려면 다음을 실행한다.

```powershell
.\packaging\one_chip_run_pack\07_verify_calibration.bat
```

직접 명령:

```powershell
.\.venv\Scripts\python.exe scripts\verify_one_chip_calibration.py --write-overlays
```

검증 내용:

- `calibration/calibration.json` 기본 구조 확인
- 원본 YAML에서 다시 생성한 calibration과 `intrinsic`, `T_camera_reference`, image size, distortion model 비교
- `MERGED` LiDAR transform이 identity인지 확인
- `CAM_LEFT`, `CAM_RIGHT` 회전행렬의 determinant와 orthogonality 확인
- 대표 frame의 LiDAR 포인트를 각 카메라에 투영해 이미지 내부에 들어오는 비율 출력
- `artifacts/calibration_verify/`에 projection overlay JPG 생성

## 5. MCAP 변환 규칙

입력 bag 구조:

```text
E:\one_chip\rosbags\cvat_all_20260708_063100
E:\one_chip\rosbags\cvat_all_20260708_063701
```

각 bag에서 읽는 파일:

```text
lidar/lidar_0.mcap
cam_left/cam_left_0.mcap
cam_right/cam_right_0.mcap
```

토픽:

| sensor | topic |
|---|---|
| MERGED | `/iv_points_10hz` |
| CAM_LEFT | `/cam_left/pylon_ros2_camera_node/image_raw` |
| CAM_RIGHT | `/cam_right/pylon_ros2_camera_node/image_raw` |

LiDAR BIN column:

```text
x, y, z, intensity, elongation, scan_id, scan_idx, is_2nd_return
```

카메라 원본은 `bayer_gbrg8`이고, 기본 변환은 빠른 block demosaic로 JPG를 만든다.

## 6. GUI에서 확인할 것

1. `E:\one_chip_converted`를 연다.
2. dataset 확인 창에서 다음을 본다.
   - frame: `3754`
   - LiDAR: `MERGED`
   - camera: `CAM_LEFT`, `CAM_RIGHT`
   - source label: 없음
3. 첫 화면에서 포인트와 카메라 이미지가 보이는지 확인한다.
4. 새 박스를 하나 만든다.
5. camera layer에서 `현재 3D 박스 실시간 투영`을 켠 상태로 projection 위치를 확인한다.

기존 source label이 없으므로 처음에는 object list가 비어 있는 것이 정상이다.

## 7. 문제 해결

### output already exists

변환기는 기존 dataset을 덮어쓰지 않는다. 재변환하려면 `E:\one_chip_converted`를 직접 백업하거나
스크립트 상단의 `DEFAULT_OUTPUT_ROOT`를 다른 이름으로 바꾼다. 한 번만 다른 output을 쓰려면
명령줄 옵션을 사용할 수도 있다.

```powershell
.\.venv\Scripts\python.exe scripts\convert_one_chip_dataset.py --output E:\one_chip_converted_v2
```

### session lock 경고

GUI가 이미 같은 dataset을 열고 있으면 다음 파일이 생긴다.

```text
E:\one_chip_converted\annotations\lidar_label_tool\.session.lock
```

먼저 열린 GUI를 닫고 다시 실행한다. 비정상 종료로 남은 stale lock은 앱이 PID를 확인한 뒤
교체한다.

### missing camera warning

`sync_tolerance_ms`가 너무 낮으면 nearest camera sample이 제외되어 warning이 생긴다.
이번 데이터는 70 ms에서 모든 frame이 양쪽 camera와 매칭됐다.

`--timestamp-source header`를 그대로 사용했는데 모든 camera가 빠진다면 header clock epoch가 센서마다
다른 경우다. 이 데이터는 `--timestamp-source header_aligned`를 사용해야 한다.

### projection이 안 맞아 보일 때

확인 순서:

1. `calibration/calibration.json`의 `metadata.camera_frame_convention` 확인
2. `CAM_LEFT`와 `CAM_RIGHT`를 각각 전환해서 같은 방향으로 틀어지는지 확인
3. 움직이는 객체는 timestamp delta, rolling shutter, motion compensation 미적용 때문에 오차가 날 수 있음을 감안
4. 필요하면 `--camera-frame-convention as_provided`로 calibration만 다시 만들어 비교

## 8. 다른 실험실 PC에서 사용하기

프로젝트 저장소를 다른 PC에 clone 또는 pull한 뒤 Windows에서는 `setup_windows.bat`,
Linux에서는 `./setup_linux.sh`를 한 번 실행한다. 이후 OS별 run 스크립트에서 원본과 export
경로를 직접 선택한다.

대용량 dataset인 `E:\one_chip_converted`는 저장소에 포함하지 않고 별도 저장장치나 실험실
공유 스토리지로 전달한다. 자세한 절차는 `docs/31_LAB_SOURCE_SETUP.md`를 따른다.
