# 범용 데이터셋 v2 계약

이 문서는 범용 데이터 폴더 구성, timestamp 동기화, 단일 LiDAR 편집 프로필,
작업 라벨 identity의 확정 계약이다. 기존 `dataset.json` 1.0과 Waymo 호환 adapter는
읽기 호환을 위해 유지하지만, 새 데이터셋 구성 마법사는 이 문서의 2.0 형식만 생성한다.

현재 구현에는 v2 schema/domain/reader/semantic validator뿐 아니라 폴더 discovery, 구성 마법사,
deterministic sync, runtime adapter, profile별 label repository, profile 추가와 generation 기반
재동기화가 연결되어 있다. 다음 명령으로 원본을 수정하지 않고 v2 구성을 검사할 수 있다.

```powershell
.\.venv\Scripts\python.exe -m lidar_label_tool validate-v2 C:\data\my_dataset --json
```

종료 코드는 `0`(정상), `1`(LiDAR 작업을 막지 않는 warning), `2`(계약 위반 error)다.
실제 장비 데이터와 공식 Python 3.12 기반 clean Windows PC 인증은 별도 운영 Gate로 계속
추적한다.

## 1. 규범 용어

- **MUST**: 구현과 데이터가 반드시 지켜야 한다.
- **MUST NOT**: 구현과 데이터가 해서는 안 된다.
- **SHOULD**: 특별한 이유가 없으면 지켜야 한다.
- **dataset root**: 원본 LiDAR, 이미지, timestamp가 있는 읽기 대상 루트다.
- **configuration root**: `dataset.json`, taxonomy, 생성된 frame index가 있는 루트다.
  일반적으로 dataset root와 같고, 읽기 전용 원본에서는 외부 workspace가 된다.
- **profile**: 편집 세션 하나의 LiDAR, 선택적 카메라, 동기화 index를 묶는 단위다.

## 2. 확정 정책

1. 데이터셋에는 label-ready LiDAR 후보를 하나 이상 등록할 수 있다.
2. 한 profile과 한 편집 세션의 활성 LiDAR는 정확히 하나다.
3. 앱은 여러 LiDAR를 자동 병합하거나 동시에 box fitting에 사용하지 않는다.
4. 다른 LiDAR를 라벨링하려면 다른 profile로 연다.
5. profile의 논리 카메라는 0개 또는 1개다.
6. 카메라나 calibration이 없어도 정상 LiDAR frame은 모두 라벨링할 수 있다.
7. timestamp nearest 결과는 사용자가 QA를 확인한 뒤 frame index로 확정한다.
8. 런타임은 확정된 frame index를 읽으며 데이터셋을 열 때마다 nearest를 재계산하지 않는다.
9. sync 실패 또는 카메라 누락 때문에 LiDAR frame을 삭제하지 않는다.
10. 원본 point, image, timestamp, source label은 읽기 전용으로 취급한다.
11. v2 adapter는 기존 전역 `merge_lidars_when_enabled` 설정을 무시하고 profile의 LiDAR 하나만
    로드한다. 기존 다중 LiDAR checkbox는 v2 세션에서 숨기거나 비활성화한다.

## 3. 디렉터리 구조

구성 파일과 원본이 같은 위치에 있는 기본 형태다.

```text
dataset/
├─ dataset.json
├─ generations/
│  └─ generation-000001/
│     ├─ taxonomy.json
│     └─ sync/
│        ├─ aeva_profile.frames.jsonl
│        └─ lidar_points_profile.frames.jsonl
├─ sensors/
│  ├─ lidar/
│  │  ├─ AEVA/frames/*.bin
│  │  └─ LIDAR_POINTS/frames/*.bin
│  └─ camera/
│     └─ HEAD_CAMERA/images/*.jpg
├─ timestamps/
│  ├─ AEVA.csv
│  ├─ LIDAR_POINTS.csv
│  └─ HEAD_CAMERA.csv
├─ calibration/                 # 선택
├─ source_labels/               # 선택, 읽기 전용
├─ annotations/
│  └─ lidar_label_tool/
│     ├─ aeva_profile/aeva/*.json
│     └─ lidar_points_profile/lidar_points/*.json
└─ exports/
```

읽기 전용 원본에서는 configuration root를 외부 workspace에 둔다.

```text
workspace/<dataset_id>/
├─ dataset.json                 # data_root가 원본 절대 경로를 명시
├─ generations/generation-000001/
│  ├─ taxonomy.json
│  └─ sync/*.frames.jsonl
└─ annotations/lidar_label_tool/<profile_id>/<label_lidar_id>/*.json
```

절대 `data_root`는 사용자가 선택한 로컬 원본에 대해 앱이 생성한 외부 manifest에서만 허용한다.
일반 sensor pattern에 절대 경로나 `..`를 넣어 이 경계를 우회하면 안 된다.

## 4. Dataset identity와 profile identity

`dataset_id`는 저장 namespace와 provenance에 쓰는 안정적인 machine ID다.

- 소문자 ASCII 영문/숫자로 시작하고 소문자 영문/숫자/`.`/`_`/`-`만 사용한다.
- 최대 64자다.
- 마지막 문자는 `.`일 수 없고 Windows 예약 이름 `con`, `prn`, `aux`, `nul`,
  `com1`~`com9`, `lpt1`~`lpt9`와 그 확장자 형태를 사용할 수 없다.
- 구성 마법사는 기본적으로 `ds_<uuid-hex>`를 한 번 생성한다. 절대 경로나 폴더명에서 다시
  계산하지 않으므로 데이터 폴더를 옮겨도 ID가 바뀌지 않는다.
- 첫 작업 라벨이 만들어진 뒤 변경할 수 없다.
- 한글 폴더명은 `display_name`에 보존하고 `dataset_id`로 직접 사용하지 않는다.

`profile_id`는 한 LiDAR 편집 sequence의 안정적인 machine ID다.

- 한 profile은 `lidar_id` 하나를 가진다.
- `camera`는 null 또는 단일 camera 설정이다.
- `profile_id`, `lidar_id`, 선택 LiDAR `coordinate_frame`, 좌표 계약은 첫 라벨 저장 후 변경할 수 없다.
- 현재 활성 profile은 사용자 workspace 설정에 저장한다. `dataset.json`은
  `default_profile_id`만 가지며 profile 전환 때마다 수정하지 않는다.
- `manifest_revision`은 1부터 시작하고 설정 generation을 성공적으로 commit할 때만 증가한다.
- profile은 활성 frame index의 경로, 전체 SHA-256, frame 수와 생성 방법을 manifest에 기록한다.

## 5. 좌표·단위 계약

모든 v2 LiDAR는 importer에서 다음 label-ready 좌표로 정규화되어 있어야 한다.

- 위치와 크기: meter
- x: forward
- y: left
- z: up
- yaw 축: +z
- yaw 단위: radian
- yaw 0: box length 축이 +x
- 양의 yaw: +x에서 +y로 반시계 방향
- box `[x, y, z]`: 기하 중심
- size `[length, width, height]`: local x/y/z, 모두 양수

앱은 좌표축이나 단위를 파일 내용만으로 추측하지 않는다. metadata로 확인되지 않으면
구성 마법사에서 사용자가 명시적으로 확인해야 한다.

## 6. LiDAR 계약

- 지원 형식: dense float32 BIN, PCD v0.7 ASCII, PCD uncompressed binary
- 한 profile의 한 frame에는 label-ready point 파일 하나만 사용한다.
- BIN은 `point_columns`, `point_dtype`, `byte_order`를 manifest에 선언한다.
- `point_columns`에는 중복 없이 `x`, `y`, `z`가 반드시 포함되어야 한다.
- BIN byte 수는 `4 * column_count`의 배수여야 한다.
- PCD `binary_compressed`는 v2 1차 범위에서 지원하지 않는다.
- 원본 sample ID는 센서 내부에서 유일해야 하며 원본 파일을 rename하지 않는다.
- frozen frame index의 LiDAR `sample_id`는 경로에 안전한 **논리 sample ID**다. 원본 ID가 machine ID
  문법을 만족하면 그대로 사용한다.
- 원본 stem이 안전하지 않으면 구성 서비스가 결정적인 논리 sample ID를 한 번 생성한다. 원본 ID는
  `source_sample_id`, 실제 파일은 `path`에 보존하며 이후 재동기화에서 다시 번호를 붙이지 않는다.
- 논리 ID 생성값은 `s_`와
  `SHA-256(UTF-8(sensor_id + "\\0" + source_sample_id + "\\0" + POSIX-relative-path))`의 앞
  62개 소문자 hex를 이어 만든 64자 문자열이다. 생성 충돌은 자동 suffix로 숨기지 않고 오류다.
- `data_pattern`의 `{sample_id}`는 원본 파일을 발견하는 source sample ID 자리다. 런타임 로드는
  pattern을 다시 추측하지 않고 frozen frame index의 명시적 `path`를 사용한다.

원본 LiDAR가 여러 개여도 앱이 병합하지 않는다. 이미 외부에서 병합된 cloud는 하나의
논리 LiDAR 후보로 등록한다.

## 7. 카메라 계약

- 데이터셋의 논리 카메라는 없거나 하나다.
- 지원 형식: JPEG, PNG
- 여러 물리 카메라를 외부에서 합친 이미지는 하나의 논리 camera로 등록할 수 있다.
- 단순 합성 이미지는 자동으로 pinhole calibration을 가진 것으로 간주하지 않는다.
- `display_only`: 이미지만 표시하고 3D projection을 하지 않는다.
- `calibrated`: profile의 calibration 파일이 유효할 때만 projection을 한다.
- calibration이 없거나 손상되어도 LiDAR 편집은 계속하고 projection만 비활성화한다.
- frame index의 camera도 경로에 안전한 논리 `sample_id`, 원본 `source_sample_id`, 실제 `path`를
  함께 저장한다. 원본 ID가 안전하지 않을 때는 LiDAR와 같은 hash 규칙으로 논리 ID를 만든다.

모든 변환 행렬은 `T_target_source` 의미를 유지한다.

```text
p_target = T_target_source @ p_source
```

## 8. Timestamp CSV 계약

센서 timestamp는 선택 사항이다. 카메라를 timestamp nearest로 연결하려면 선택 LiDAR와
카메라 모두 timestamp spec을 가져야 한다.

```csv
sample_id,bag_time_ns
000000,1778225784354747202
000001,1778225784464672272
```

manifest timestamp spec은 다음을 명시한다.

- `path`: dataset root 기준 POSIX 상대 경로
- `sample_id_column`: sample ID 컬럼
- `value_column`: 선택 timestamp 컬럼
- `unit`: `ns`, `us`, `ms`, `s`
- `clock_domain`: `bag`, `header`, `device`, `unix` 또는 명시적인 사용자 정의 ID
- `offset_ns`: 명시적 정수 보정값. 보정하지 않으면 `0`
- `sha256`: 구성 시 읽은 timestamp CSV의 소문자 SHA-256

CSV의 sample ID는 frame index의 `source_sample_id`와 연결한다. 선행 0을 잃지 않도록 항상
문자열로 파싱하며 UTF-8 BOM은 허용하되 저장 시에는 UTF-8 no-BOM으로 정규화한다.

내부 계산은 정수 `timestamp_ns`로 통일하고 float로 변환하지 않는다. nearest 입력 두 센서는
동일 clock domain이어야 한다. 다른 domain을 앱이 암묵적으로 정렬하거나 offset을 추정하지 않는다.

## 9. 동기화 계약

profile의 sync method는 다음 중 하나다.

- `lidar_only`: 카메라 없음. LiDAR sample ID 기준으로 index 생성
- `exact_stem`: 동일한 원본 `source_sample_id`의 LiDAR와 카메라를 연결
- `timestamp_nearest`: LiDAR timestamp에 가장 가까운 camera timestamp 연결

`timestamp_nearest` 규칙:

1. LiDAR가 anchor이고 모든 유효 LiDAR sample을 frame으로 보존한다.
2. `abs(camera_timestamp_ns - lidar_timestamp_ns) <= tolerance_ns`일 때만 연결한다.
3. 정확히 같은 차이의 camera 후보가 둘이면 더 이른 timestamp를 선택한다. timestamp도 같으면
   POSIX 상대 `path`의 UTF-8 byte 순서가 앞선 sample을 선택한다.
4. camera sample 재사용은 허용하지만 반복 횟수와 최대 연속 길이를 QA에 표시한다.
5. 범위 밖 또는 손상된 camera sample은 null로 기록한다.
6. frame ID는 LiDAR 논리 sample ID와 같으며 재동기화로 바꾸지 않는다.
7. 입력 순서와 관계없이 결과는 결정적이고 같은 입력으로 byte-identical해야 한다.

timestamp는 manifest의 단위를 정수 ns로 바꾼 뒤 `offset_ns`를 더해 비교한다. LiDAR timestamp가
있으면 frame은 `(effective timestamp, logical sample ID)` 오름차순, 없으면 logical sample ID의
UTF-8 byte 순서로 정렬하고 `ordinal`을 0부터 붙인다. 중복 LiDAR 원본 sample ID는 자동
합치거나 덮어쓰지 않고 구성 오류로 처리한다.

사용자는 match 수, 누락 수, 평균/p95/최대 delta, 반복 camera sample, 비단조·중복 timestamp를
확인한 후 적용한다. 적용된 결과는 `schemas/frame-index-v2.schema.json`에 맞는 JSONL로 저장한다.

## 10. dataset.json v2

정식 형식은 `schemas/dataset-v2.schema.json`을 따른다. 예시는 다음과 같다.

```json
{
  "schema_version": "2.0",
  "dataset_id": "ds_7d30c92f",
  "display_name": "광기술원 동적 차량 데이터",
  "manifest_revision": 1,
  "layout": "device_centric_v2",
  "data_root": {"kind": "manifest_relative", "path": "."},
  "coordinate_system": {
    "unit": "meter",
    "x_axis": "forward",
    "y_axis": "left",
    "z_axis": "up",
    "yaw_axis": "+z",
    "yaw_unit": "radian",
    "yaw_zero": "+x",
    "yaw_direction": "counterclockwise",
    "box_center": "geometric_center"
  },
  "labeling_policy": {
    "active_lidar": "one_per_profile",
    "merge_lidars": false,
    "label_namespace": "profile_lidar",
    "frame_id_policy": "logical_lidar_sample_id"
  },
  "lidars": [
    {
      "id": "aeva",
      "display_name": "AEVA",
      "coordinate_frame": "lidar:AEVA",
      "format": "bin",
      "data_pattern": "sensors/lidar/AEVA/frames/{sample_id}.bin",
      "point_columns": ["x", "y", "z", "velocity", "intensity"],
      "point_dtype": "float32",
      "byte_order": "little-endian",
      "timestamp": {
        "format": "csv",
        "path": "timestamps/AEVA.csv",
        "sample_id_column": "sample_id",
        "value_column": "bag_time_ns",
        "unit": "ns",
        "clock_domain": "bag",
        "offset_ns": 0,
        "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
      }
    }
  ],
  "camera": {
    "id": "head_camera",
    "display_name": "Head camera",
    "coordinate_frame": "camera:HEAD_CAMERA",
    "image_pattern": "sensors/camera/HEAD_CAMERA/images/{sample_id}.jpg",
    "timestamp": {
      "format": "csv",
      "path": "timestamps/HEAD_CAMERA.csv",
      "sample_id_column": "sample_id",
      "value_column": "bag_time_ns",
      "unit": "ns",
      "clock_domain": "bag",
      "offset_ns": 0,
      "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
    }
  },
  "profiles": [
    {
      "id": "aeva_profile",
      "display_name": "AEVA 라벨링",
      "lidar_id": "aeva",
      "camera": {
        "camera_id": "head_camera",
        "mode": "display_only",
        "calibration_path": null,
        "calibration_sha256": null
      },
      "frame_index": {
        "schema_version": "2.0",
        "path": "generations/generation-000001/sync/aeva_profile.frames.jsonl",
        "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
        "frame_count": 216,
        "generation": {
          "method": "timestamp_nearest",
          "tolerance_ns": 50000000
        }
      }
    }
  ],
  "default_profile_id": "aeva_profile",
  "taxonomy": {
    "schema_version": "2.0",
    "path": "generations/generation-000001/taxonomy.json",
    "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
  }
}
```

## 11. Frame index v2

generation의 `sync/*.frames.jsonl` 각 non-empty line은 독립 JSON object이고
`schemas/frame-index-v2.schema.json`을 만족해야 한다.

파일은 UTF-8 no-BOM, LF newline, 마지막 newline 포함 형식으로 쓴다. 각 record는 key를
Unicode code point 순으로 정렬한 compact JSON(`,`, `:` 뒤 공백 없음, non-ASCII escape 없음)으로
직렬화하여 같은 입력의 whole-file SHA-256이 Windows/Linux에서 같아야 한다.

```json
{"schema_version":"2.0","profile_id":"aeva_profile","ordinal":0,"frame_id":"000000","lidar":{"sensor_id":"aeva","sample_id":"000000","source_sample_id":"000000","path":"sensors/lidar/AEVA/frames/000000.bin","timestamp_ns":1778225784354747202},"camera":{"sensor_id":"head_camera","sample_id":"000000","source_sample_id":"000000","path":"sensors/camera/HEAD_CAMERA/images/000000.jpg","timestamp_ns":1778225784347166083,"delta_ns":-7581119},"match":{"method":"timestamp_nearest","status":"matched","tolerance_ns":50000000}}
```

카메라가 없거나 매칭되지 않으면 `camera`는 null이다. `lidar.timestamp_ns`는 timestamp가 없는
`lidar_only` 또는 `exact_stem` profile에서 null일 수 있다. 각 sensor의 `path`가 실제 runtime
입력이고 `data_pattern`은 discovery 및 index 검증에만 사용한다.

`match` 조합은 다음으로 고정한다.

| method | camera | status | tolerance_ns |
|---|---|---|---|
| `lidar_only` | null | `not_requested` | null |
| `exact_stem` | object/null | `matched`/`unmatched` | null |
| `timestamp_nearest` | object/null | `matched`/`unmatched` | 0 이상 정수 |

`timestamp_nearest`의 matched record는 두 timestamp와 `delta_ns`가 모두 정수여야 하고,
`delta_ns = camera.timestamp_ns - lidar.timestamp_ns` 및 tolerance 조건을 만족해야 한다.

## 12. 작업 라벨 v2 identity

작업 라벨은 `schemas/label-v2.schema.json`을 따른다. 저장 key는 다음 네 값이다.

```text
dataset_id + profile_id + label_lidar_id + frame_id
```

namespace root와 저장 경로는 다음으로 고정한다.

```text
sidecar namespace_root = <dataset_root>
external namespace_root = <workspace_root>/<dataset_id>

<namespace_root>/annotations/lidar_label_tool/<profile_id>/<label_lidar_id>/<frame_id>.json
```

최소 예시는 다음과 같다.

```json
{
  "schema_version": "2.0",
  "dataset_id": "ds_7d30c92f",
  "profile_id": "aeva_profile",
  "label_lidar_id": "aeva",
  "frame_id": "000000",
  "label_lidar_sample_id": "000000",
  "revision": 1,
  "frame_status": "in_progress",
  "saved_at_utc": "2026-08-07T01:23:45Z",
  "point_cloud_path": "sensors/lidar/AEVA/frames/000000.bin",
  "image_path": "sensors/camera/HEAD_CAMERA/images/000000.jpg",
  "reference_frame": "lidar:AEVA",
  "coordinate_system": {
    "unit": "meter",
    "x_axis": "forward",
    "y_axis": "left",
    "z_axis": "up",
    "yaw_axis": "+z",
    "yaw_unit": "radian",
    "yaw_zero": "+x",
    "yaw_direction": "counterclockwise",
    "box_center": "geometric_center"
  },
  "provenance": {
    "source_format": "device_centric_v2",
    "source_paths": [],
    "source_fingerprints": {},
    "dataset_manifest": {
      "path": "dataset.json",
      "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
    },
    "profile_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    "frame_index": {
      "path": "generations/generation-000001/sync/aeva_profile.frames.jsonl",
      "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "lidar_binding_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "frame_record_sha256": "0000000000000000000000000000000000000000000000000000000000000000"
    },
    "taxonomy": {
      "path": "generations/generation-000001/taxonomy.json",
      "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
    },
    "point_cloud_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    "image_sha256": "0000000000000000000000000000000000000000000000000000000000000000"
  },
  "calibration_state": {
    "requested_mode": "display_only",
    "effective_mode": "display_only",
    "path": null,
    "fingerprint": null,
    "status": "not_configured"
  },
  "objects": [
    {
      "id": "object_001",
      "class_id": "car",
      "box3d": {
        "x": 10.0,
        "y": 1.0,
        "z": 0.8,
        "length": 4.2,
        "width": 1.8,
        "height": 1.6,
        "yaw": 0.0
      }
    }
  ]
}
```

다음 identity 필드는 첫 저장 후 immutable이다.

- `dataset_id`
- `profile_id`
- `label_lidar_id`
- `frame_id`
- `reference_frame`
- `coordinate_system`
- `frame_id -> label_lidar_sample_id -> point_cloud_path` 결합

프레임 간 수동 객체 연결은 위 frame/profile identity를 바꾸지 않는다. 사용자가 기준 객체를
기억하고 명시적으로 실행한 경우에만 현재 frame의 object `id`를 기준 ID로 변경하거나 박스를
복사할 수 있다. 같은 profile/LiDAR/reference frame 안에서만 허용하며 대상 frame에 이미 같은
ID가 있으면 거부한다. 기존 객체 연결은 class 일치가 필요하고 box/attributes/source는 보존한다.

선택적 object 확장 필드 `object_link_history`는 순서가 있는 배열이며 각 항목에 `operation`
(`copy`/`link`), `previous_object_id`, `reference_object_id`, `reference_frame_id`, `linked_at_utc`를
기록한다. 기존 이력과 알 수 없는 field를 유지하고 잘못된 기존 이력 형식은 덮어쓰지 않는다.
복사/연결은 현재 frame의 단일 편집·undo이며 일반 원자 저장을 사용한다. 다른 frame의 파일이나
원본 source 파일은 변경하지 않는다.

분할 폴더의 연속 데이터를 위한 `이전 폴더의 객체 가져오기…`는 별도의 명시적 **객체 단위**
복사다. 저장된 v1/v2 작업 JSON을 schema 검증한 뒤 선택 객체만 현재 frame에 추가한다.
dataset/profile ID는 달라도 되지만 LiDAR ID와 reference frame이 같아야 하며 §5의 좌표·단위·yaw
계약을 만족해야 한다. v1의 축 표기는 기존 v1 계약의 meter/radian/기하 중심 의미로 해석하며
좌표를 변환하거나 새로운 단위를 추정하지 않는다. class key는 대상 catalog와 정확히 일치해야
하고 자동 remapping은 하지 않는다. 현재 frame에 이미 있는 ID는 기존 객체를 유지하며 건너뛴다.

추가 객체의 ID·class·box·attributes·source·unknown field는 보존하고, 현재 frame의 identity,
point/image binding, provenance, calibration context와 revision은 유지한다. 선택적 object 확장
필드 `object_transfer_history` 배열에 `operation: "dataset_transfer"`, `source_dataset_id`,
`source_profile_id`(v1은 null), `source_frame_id`, `source_object_id`, `source_label_name`,
`source_label_sha256`, `imported_at_utc`를 추가한다. 기존 이력을 보존하고 배열이 아닌 이력은 거부한다.
미리보기 이후 source 파일 hash와 현재 frame snapshot/request generation을 다시 검사한다.
전체 추가는 하나의 Undo이며 저장은 대상 repository만 수행한다. 이 이력이 있는 객체는 명시적
이어받기 대상으로 취급한다. 원본 JSON에 기록된 데이터 경로를 따라가거나 source 파일을 쓰지 않는다.

선택 객체의 1-step 추적 보조(D42~D43)는 동일 profile의 순차 다음 frame에서 **새로 이어받은**
객체의 x/y/z만 편집한다. 사용자의 opt-in이 필요하며 기존 대상 객체 ID와 복구 라벨은 보존한다.
length/width/height/yaw와 class/source/unknown field, frame identity·binding·revision은 바꾸지 않는다.
z는 기본적으로 객체 포인트의 상대 이동량이고 지면 접촉을 암묵적으로 가정하지 않는다.
지면 보정은 실행 중 객체 ID별 별도 opt-in이며 지면 근거 부족 시 이전 z를 유지한다.

적용 근거는 선택적 object 배열 `tracking_history`에 `method: "local_point_translation"`,
`source_frame_id`, `target_frame_id`, `delta_xyz`, `score`, `adjust_z`, `ground_contact`,
`ground_applied`, `applied_at_utc`로 기록한다. 이 method의 기록은 현재 frame의 마지막 적용 한 건만
유지하고 이전 frame의 기록은 그 frame 라벨에 남긴다. 다른 method의 이력과 알 수 없는 metadata는
보존한다. 배열이 아닌 기존 이력은 덮어쓰지 않는다. 추적 성공은 reviewed를 의미하지 않으며
사용자가 확인·수정한 뒤 일반 원자 저장을 사용한다.

라벨 provenance에는 다음 fingerprint를 기록한다.

- dataset manifest SHA-256
- canonical profile SHA-256
- profile frame index SHA-256
- 현재 LiDAR binding SHA-256
- 현재 전체 frame record SHA-256
- taxonomy SHA-256
- 활성 point cloud SHA-256
- 연결된 image SHA-256 또는 null
- calibration SHA-256 또는 null
- 존재하는 source label fingerprint

manifest 또는 sync fingerprint가 달라지면 저장 라벨을 조용히 재해석하지 않고 재검토 경고를
표시한다. profile의 LiDAR, reference frame, coordinate system 또는 LiDAR binding이 다르면
load/save를 거부한다. 카메라 binding만 바뀌면 라벨은 유지하되 이미지 재검토를 요구한다.

canonical profile SHA-256 입력은 정확히 `dataset_id`, `profile_id`, `frame_id_policy`, dataset
`coordinate_system`과 LiDAR의 `id`, `coordinate_frame`, `format`, `point_columns`,
`point_dtype`(없으면 null), `byte_order`(없으면 null)다. camera, calibration, frame index 경로,
timestamp, display name은 이 hash에 넣지 않는다.

```text
{
  "dataset_id": <dataset.dataset_id>,
  "profile_id": <profile.id>,
  "frame_id_policy": <dataset.labeling_policy.frame_id_policy>,
  "coordinate_system": <dataset.coordinate_system object>,
  "lidar": {
    "id": <lidar.id>,
    "coordinate_frame": <lidar.coordinate_frame>,
    "format": <lidar.format>,
    "point_columns": <lidar.point_columns>,
    "point_dtype": <lidar.point_dtype or null>,
    "byte_order": <lidar.byte_order or null>
  }
}
```
Recovery snapshot은 `dataset_id`, `profile_id`, `label_lidar_id`, `frame_id`, `reference_frame`,
`base_revision`을 저장하고 embedded label identity까지 같은 경우에만 복구한다. profile namespace의
`.session.lock`은 `dataset_id`, `profile_id`, `label_lidar_id`, `reference_frame`, `profile_sha256`와
PID/host/owner를 저장하며 `frame_id`나 `base_revision`을 갖지 않는다. lock scope는
`<profile_id>/<label_lidar_id>` 전체다. 파일 구조는 각각 `schemas/recovery-v2.schema.json`과
`schemas/session-lock-v2.schema.json`을 따른다.

semantic fingerprint 입력은 UTF-8, 정렬 key, compact separator, non-ASCII escape 없음의 canonical
JSON으로 직렬화한 뒤 SHA-256을 계산한다. `lidar_binding_sha256` 입력은 정확히 `profile_id`,
`frame_id`, LiDAR의 `sensor_id`, 논리 `sample_id`, `source_sample_id`, `path`다.
`frame_record_sha256`은 frame-index JSON object 전체를 같은 방식으로 canonicalize한 값이다.
따라서 LiDAR binding 변경은 fatal, camera/timestamp/ordinal만 바뀐 전체 record 변경은 재검토
warning으로 구분한다. 파일 fingerprint는 canonical JSON이 아니라 디스크의 원본 byte 전체를
그대로 해시한다.

```text
{
  "profile_id": <record.profile_id>,
  "frame_id": <record.frame_id>,
  "lidar": {
    "sensor_id": <record.lidar.sensor_id>,
    "sample_id": <record.lidar.sample_id>,
    "source_sample_id": <record.lidar.source_sample_id>,
    "path": <record.lidar.path>
  }
}
```

## 13. Taxonomy

v2 manifest의 `taxonomy` 객체는 schema version, generation 경로와 SHA-256을 함께 기록하며
`schemas/taxonomy.schema.json` 형식을 참조한다.
`class_id`는 라벨에서 사용하는 안정적인 machine key이며 작업 중 rename하지 않는다. 표시 이름,
색상, 기본 크기, 단축키는 taxonomy가 관리한다. class ID, alias, shortcut 중복과 존재하지 않는
mapping target은 runtime validator가 거부한다.

## 14. 생성·저장 transaction

`dataset.json`, taxonomy, frame index를 서로 다른 세대로 섞어서는 안 된다.

1. 새 taxonomy와 frame index를 고유한 generation 경로에 쓴다.
2. 각 파일을 flush/fsync하고 schema로 검증한다.
3. 실제 대표 point와 이미지를 로드하고 preflight를 수행한다.
4. 기존 파일 fingerprint가 scan 시점과 같은지 확인한다.
5. 모든 참조가 새 generation을 가리키는 `dataset.json`을 마지막에 원자 교체한다.
6. 실패·취소 시 임시 파일을 제거하고 기존 manifest/index/label을 유지한다.

원본 point, image, timestamp, source label은 생성·재동기화 과정에서 수정하지 않는다.

commit 전에는 기존 v2 label과 recovery를 모두 조사한다. 라벨이 시작된 namespace에서는 다음을
일반 설정 편집으로 변경할 수 없으며 새 profile 또는 명시적 migration이 필요하다.

- dataset/profile ID 변경, 기존 profile 삭제, profile LiDAR 변경
- LiDAR coordinate frame 또는 dataset coordinate system 변경
- point format/dtype/byte order/columns 변경
- 라벨이 있는 frame 제거 또는 `frame_id -> LiDAR sample/source sample/path` 변경
- 라벨이 있는 frame의 point cloud byte SHA-256 변경
- 사용 중인 taxonomy class ID 삭제 또는 다른 의미로 재매핑

camera match, image, timestamp, ordinal, calibration 변경은 LiDAR binding을 유지한 경우에만 허용하고
old/new diff와 영향받는 라벨 수를 보여준 뒤 재검토 상태로 표시한다. 작업 label, recovery 또는
migration report가 참조하는 generation은 삭제하지 않는다. 활성 manifest가 참조하지 않고 어떤
작업 산출물에서도 참조하지 않는 generation만 명시적 정리 대상으로 삼는다.

## 15. JSON Schema 밖의 runtime 검증

JSON Schema만으로 다음 교차 참조와 파일 시스템 조건을 완전히 검증할 수 없으므로
manifest validator와 preflight가 반드시 검사한다.

- sensor/profile/class ID의 전체 고유성과 Windows case-fold 충돌·예약 이름
- `default_profile_id`가 실제 profile을 가리키는지
- profile `lidar_id`와 `camera_id`가 선언된 sensor를 가리키는지
- `record.profile_id == profile.id`
- `record.lidar.sensor_id == profile.lidar_id`
- `record.frame_id == record.lidar.sample_id`
- `label.profile_id == record.profile_id`
- `label.label_lidar_id == record.lidar.sensor_id`
- `label.frame_id == record.frame_id`
- `label.label_lidar_sample_id == record.lidar.sample_id`
- profile의 선택 LiDAR coordinate frame과 작업 label reference frame 일치
- `timestamp_nearest` profile의 두 sensor timestamp 존재와 동일 clock domain
- `display_only`/`calibrated`와 calibration path 상태 일치
- data/config path containment와 symlink escape
- source sample ID, 논리 sample ID, frame ID 중복과 실제 파일 존재
- `frame_id == lidar.sample_id == label_lidar_sample_id`
- label의 `point_cloud_path`가 frozen LiDAR path와 같고 `image_path`가 camera path/null과 같은지
- frame index의 profile/sensor/sample 참조, 0부터 연속인 ordinal, frame 수와 whole-file hash
- match method/status/camera/timestamp/tolerance/delta 조합과 결정적 정렬
- BIN stride, PCD payload, 이미지 decode
- manifest/index/taxonomy/calibration/active point fingerprint와 canonical profile/LiDAR
  binding/frame record hash 일치
- label object ID 중복과 모든 `class_id`의 taxonomy 존재 여부
- image fingerprint 불일치는 LiDAR 저장을 막지 않되 이미지 재검토 warning

## 16. v1 호환과 migration

아래 전체-frame migration은 구현 시 지켜야 할 계약이며, 현재 전용 migrator/실행 메뉴가
완성되었다는 뜻은 아니다. 현재 제공하는 §12의 객체 단위 가져오기와 구분한다.

- 기존 `dataset.json` 1.0과 `label.schema.json` 1.0은 계속 읽는다.
- 파일 내용을 domain model로 읽기 전에 `schema_version`으로 parser와 repository를 dispatch한다.
- v2 repository는 exact profile/LiDAR namespace의 v2 label만 읽고 쓴다. 손상된 v2 파일이 있으면
  v1/source label로 fallback하지 않으며, v2를 v1 writer로 저장하거나 메모리에서 자동 변환하지 않는다.
- v1 **전체 frame 라벨**을 v2로 이관하는 유일한 경로는 전용 migrator다. §12의 명시적 객체
  가져오기는 대상 frame에 대한 편집이며 이전 frame 라벨의 identity/revision/provenance를 이관하지 않는다.
- 새 구성 마법사는 v1을 생성하지 않는다.
- v1 라벨은 dataset ID가 같고 대상 profile/LiDAR/reference frame/LiDAR binding이 하나로 증명되며
  대상 v2 파일이 없을 때만 사용자의 확인 후 이관할 수 있다.
- LiDAR가 여러 개이거나 label reference frame·point binding이 모호하거나 대상 v2 파일이 이미
  있으면 revision을 비교해 자동 선택하지 않고 이관을 중단한다.
- 이관 전 원본 v1 라벨과 `.bak`을 보존하고 결과를 새 profile namespace에 쓴다.
- reference frame이 다르면 metadata만 바꾸지 않고 별도의 box 좌표 변환 migration으로 처리한다.
- v1 recovery를 v2 profile에 자동 적용하지 않는다.
- Waymo와 one_chip 전용 흐름은 호환/레거시 경로로 유지하며 v2 범용 서비스의 기본 동작에
  섞지 않는다.

v1 `dataset_id`가 v2 machine ID 문법을 만족하고 충돌이 없으면 그대로 사용한다. 그렇지 않으면
migrator가 `ds_<uuid-hex>`를 한 번 생성하고 원래 값을 manifest metadata, label migration
provenance와 migration report의 `legacy_dataset_id`에 보존한다. `class_name -> class_id`는 사용자가
확인한 명시적 mapping table로만 변환한다. unmapped/ambiguous class가 있으면 fallback을 추측하지
않고 전체 계획을 중단한다. source object ID와 알 수 없는 field는 보존한다.

target revision은 `v1 revision + 1`이며 label의 `migration`에는 source schema/path/hash/revision,
migration 시각, tool version, class mapping hash를 기록한다. 전체 결과를 임시 namespace에서 schema와
semantic validator로 검사한 뒤 활성화하고 report를 저장한다. 대상 v2 파일이 이미 있고 같은 source
hash의 완료 report가 있으면 `already_migrated`로 끝내며 다시 쓰지 않는다. 그 외 기존 target은
충돌로 처리한다.

## 17. 완료 불변식

1. 한 편집 세션의 활성 LiDAR는 정확히 하나다.
2. 서로 다른 profile의 같은 frame ID 라벨은 충돌하지 않는다.
3. 카메라 또는 calibration이 없어도 LiDAR 라벨링은 가능하다.
4. sync 실패로 LiDAR frame 수와 순서를 줄이지 않는다.
5. 다른 clock domain을 조용히 nearest matching하지 않는다.
6. 생성 실패 후 기존 manifest, sync, taxonomy, 라벨과 원본 데이터가 보존된다.
7. schema와 preflight를 통과한 generation만 활성화한다.
8. 한글·공백 경로와 읽기 전용 원본 + 외부 workspace를 지원한다.
9. 기존 v1/Waymo/one_chip 데이터는 명시적인 호환 경로로 계속 열 수 있다.
