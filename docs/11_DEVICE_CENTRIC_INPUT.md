# Device 중심 입력 구조

## 권장 폴더

실제 운영 데이터는 frame 폴더를 반복하지 않고 sensor/device별로 모은다.

```text
dataset/
├─ dataset.json
├─ sensors/
│  ├─ lidar/
│  │  └─ MERGED/frames/<sample_id>.bin
│  └─ camera/
│     ├─ FRONT/images/<sample_id>.jpg
│     ├─ FRONT_LEFT/images/<sample_id>.jpg
│     └─ ...
├─ sync/
│  └─ frames.jsonl
├─ calibration/
│  ├─ calibration.json
│  └─ frames/<frame_id>.json
├─ source_labels/              # 선택: 가져온 원본 라벨
├─ annotations/
│  └─ lidar_label_tool/        # 앱 작업 라벨
└─ exports/                    # 명시적 원 포맷 export
```

앱에는 원본 LiDAR별 파일이 아니라 공통 좌표계로 사전 병합된 `MERGED` 파일 하나를 전달한다. 파일명은 연속 숫자일 필요가 없으며 sample ID 문자열로 취급한다. `.bin`과 `.pcd`를 지원한다.

## Dataset manifest 예시

```json
{
  "schema_version": "1.0",
  "dataset_id": "my_sequence_001",
  "layout": "device_centric",
  "reference_frame": "vehicle",
  "primary_lidar": "MERGED",
  "sensors": [
    {
      "id": "MERGED",
      "type": "lidar",
      "coordinate_frame": "vehicle",
      "data_patterns": {
        "return1": "sensors/lidar/MERGED/frames/{sample_id}.bin"
      },
      "point_dtype": "float32",
      "byte_order": "little-endian",
      "point_columns": ["x", "y", "z", "intensity", "elongation", "nlz_flag"]
    },
    {
      "id": "FRONT",
      "type": "camera",
      "coordinate_frame": "camera:FRONT",
      "data_patterns": {
        "image": "sensors/camera/FRONT/images/{sample_id}.jpg"
      }
    }
  ],
  "synchronization": {
    "mode": "index",
    "index_path": "sync/frames.jsonl"
  },
  "calibration_path": "calibration/calibration.json"
}
```

`coordinate_frame`은 reference frame과 같아야 한다. 원본 `lidar:TOP` 등의 sensor-local 데이터는 변환기에서 `T_reference_sensor`를 적용한 뒤 `MERGED` 파일에 기록한다.

`dataset_id`는 workspace 경로와 라벨 provenance에 쓰이는 안정적인 고유 문자열이다. 한번 작업을 시작한 뒤 변경하지 않는다. 기존 frame 중심 샘플은 adapter가 `segment.json`의 scene name으로 생성한다.

## 동기화 index

device별 sample ID나 timestamp가 다를 수 있으므로 논리 frame과 각 sensor sample의 관계를 명시한다.

```json
{"frame_id":"000000","timestamp_us":1553226705298960,"samples":{"lidar:MERGED":"000000","camera:FRONT":"000037"}}
{"frame_id":"000001","timestamp_us":1553226705398960,"samples":{"lidar:MERGED":"000001","camera:FRONT":"000038"}}
```

앱은 다음 순서로 동기화한다.

1. `frames.jsonl` index
2. 동일 stem 정확 매칭
3. 사용자가 명시적으로 켠 timestamp nearest + tolerance

자동 nearest 매칭은 조용히 잘못된 frame을 묶을 수 있어 기본 fallback으로 사용하지 않는다.

## 공통 FrameBundle

두 adapter는 동일한 `SourceFrameData`를 제공하고, service가 working label repository 결과를 합쳐 UI용 `FrameBundle`을 만든다.

```text
FrameBundle
├─ frame_id
├─ timestamp
├─ lidar_samples[sensor_id][return_id]
├─ camera_samples[sensor_id]
├─ source_coordinate_frames[sensor_id]
├─ calibration
├─ source_labels
└─ working_label
```

adapter 자체는 working label을 읽거나 저장하지 않는다. 따라서 source 저장 구조나 annotation workspace를 바꿔도 domain, geometry, UI 코드를 바꾸지 않는다.

## 지원 adapter

- `DeviceCentricAdapter`: `dataset.json`과 `exact_stem`/`frames.jsonl`을 읽는 정식 형식
- `FrameCentricWaymoAdapter`: 현재 받은 `frame_000/lidar|camera|labels` 형식

두 adapter 모두 read-only source와 별도 working annotation 경로를 제공한다.

`0000.bin`, `0001.bin`처럼 MERGED 폴더에 연속 저장하는 구조를 지원한다. 모든 장치가 같은 번호를 쓰면 `exact_stem`, 번호 또는 timestamp가 다르면 `frames.jsonl` index를 사용한다. sensor-local 원본은 라벨링 앱에 직접 넣지 않고 먼저 변환기로 reference-frame MERGED 파일을 만든다.

dataset root가 쓰기 불가능해 외부 workspace를 선택하면 `<workspace>/<dataset_id>/annotations/lidar_label_tool/` 구조를 사용하여 다른 dataset의 동일 frame ID와 충돌하지 않게 한다.
