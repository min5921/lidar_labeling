# 데이터 계약

## 원본 데이터 전달

사용자가 준비한 원본은 이름과 구조를 바꾸지 않고 다음 위치에 둔다.

```text
local_data/incoming/<dataset_name>/
```

이 폴더는 Git에서 제외한다. 먼저 실제 구조를 검사한 뒤 아래의 정규화 구조에 대응하는 dataset adapter를 만든다. 원본을 강제로 이동하거나 rename하지 않는다.

## 정식 device 중심 구조

실제 운영 입력은 sensor/device별로 저장한다. 자세한 manifest와 동기화 규칙은 `docs/11_DEVICE_CENTRIC_INPUT.md`를 따른다.

```text
dataset/
├─ dataset.json
├─ sensors/
│  ├─ lidar/
│  │  └─ MERGED/frames/<sample_id>.bin|pcd
│  └─ camera/
│     └─ <camera_id>/images/<sample_id>.jpg
├─ sync/
│  └─ frames.jsonl
├─ source_labels/             # 선택: 원본, 읽기 전용
├─ annotations/
│  └─ lidar_label_tool/       # 작업 라벨
├─ exports/                   # 명시적 export
└─ calibration/
   ├─ calibration.json
   └─ frames/<frame_id>.json    # 선택적 frame override
```

프레임 목록은 `sync/frames.jsonl`의 논리 frame을 우선 사용한다. index가 없으면 primary LiDAR sample을 기준으로 동일 stem을 매칭한다. timestamp nearest 매칭은 tolerance를 명시한 경우에만 사용한다. frame ID, sample ID, sensor ID는 문자열 그대로 보존한다.

현재 전달된 `frame_000/...` 구조는 `FrameCentricWaymoAdapter`가 지원하므로 원본 재배치가 필요 없다.

## 좌표와 단위

- reference frame 기본 이름: `vehicle`
- reference 좌표: x 전방, y 좌측, z 위
- 위치와 크기 단위: meter
- 각도 단위: 내부/JSON은 radian, UI는 degree
- yaw 축: +z
- yaw 0: 박스 length 축이 +x와 평행
- yaw 양의 방향: +z에서 원점을 내려다볼 때 +x에서 +y로 도는 반시계 방향
- 박스 `[x, y, z]`: 박스 기하학적 중심
- 크기 `[length, width, height]`: 각각 local x, local y, local z 방향이며 0보다 커야 함
- 내부 배열 순서: `[x, y, z, length, width, height, yaw]`

yaw 저장값은 `[-pi, pi)`로 정규화한다. 라벨 box는 항상 reference frame 기준이다.

## 변환 행렬 이름 규칙

모든 행렬은 `T_target_source`로 이름을 붙인다. 동차 source 좌표 `p_source`에 다음처럼 적용한다.

```text
p_target = T_target_source @ p_source
```

예를 들어 `T_vehicle_lidar_top`은 top LiDAR 점을 vehicle 좌표로 바꾼다. 이름만으로 방향이 명확하지 않은 `extrinsic`은 내부 API에서 사용하지 않는다.

## BIN 계약

- little-endian float32를 기본으로 한다.
- 한 점의 column은 manifest/schema가 선언하며 최소 `x`, `y`, `z`가 있어야 한다.
- 파일 byte 수가 `4 * column_count`의 배수가 아니면 손상 파일로 처리한다.
- 결과 shape은 `[N, column_count]`, dtype은 `numpy.float32`이다.
- 현재 샘플은 `[x, y, z, intensity, elongation, nlz_flag]`의 Nx6/24-byte stride이다.
- 각 파일의 column 수와 좌표 frame은 manifest/schema가 선언한다. 추측으로 calibration을 적용하지 않는다.
- NaN/Inf와 실제 intensity 범위는 전달 샘플 검사 후 확정한다.

loader는 raw NxC를 즉시 canonical `PointCloudData`로 분리한다. `xyz`는 항상 `[N,3]`이고 나머지는 이름별 attribute로 보존한다. renderer와 calibration 코드는 raw column index에 의존하지 않는다.

PCD는 v0.7 ASCII와 uncompressed binary를 지원한다. 운영 기본값은 용량과 로딩 속도가 유리한 little-endian float32 BIN이다. `binary_compressed` PCD는 현재 지원하지 않는다.

정식 운영 입력은 frame당 `MERGED` LiDAR 파일 한 개다. 여러 원본 LiDAR의 extrinsic 적용과 병합은 전처리 단계에서 수행하며, 결과 파일의 좌표계가 manifest `reference_frame`과 같아야 한다.

## 라벨 JSON

- UTF-8, 들여쓰기 2칸, JSON object
- 한 프레임당 작업 라벨 `annotations/lidar_label_tool/<frame_id>.json`
- `schema_version`과 `reference_frame`을 저장한다.
- stable `dataset_id`를 저장하여 외부 workspace의 frame ID 충돌을 막는다.
- `point_cloud_paths`는 sensor ID별 return 파일 배열을 가진 데이터셋 상대 경로 map이다.
- `image_paths`는 camera ID별 이미지 경로 map이다.
- path는 데이터셋 루트 기준 POSIX 형태 상대 경로이다.
- object `id`는 문자열이다. source ID를 그대로 보존하고 새 객체는 UUID 문자열을 사용한다.
- 알 수 없는 attributes는 가능한 한 보존한다.
- 작업 라벨에는 revision, 저장 시각, source fingerprint, calibration fingerprint를 기록한다.

형식 검증은 `schemas/label.schema.json`을 따른다.

## 라벨 저장 위치와 우선순위

1. 작업 라벨 `<annotation_root>/<dataset_id>/annotations/lidar_label_tool/<frame_id>.json`
2. 기존 source 3D label import
3. 라벨 없음

source label은 읽기 전용으로 취급한다. 편집 결과는 작업 라벨에 atomic 저장한다. Waymo-style 등 원래 구조가 필요하면 사용자가 명시적으로 선택한 별도 export 폴더에 생성한다.

dataset 내부 sidecar 저장을 선택한 경우 `annotation_root/dataset_id` 부분은 dataset root 자체로 축약할 수 있다. 외부 workspace를 쓸 때는 segment마다 반복되는 `frame_000`이 충돌하지 않도록 manifest ID 또는 안정적인 dataset fingerprint를 `dataset_id`로 사용한다.

데이터셋 위치가 쓰기 불가능하면 앱은 조용히 AppData로 저장하지 않고 사용자에게 별도 annotation workspace를 선택하게 한다.

저장 직전 디스크의 revision/fingerprint가 마지막 로드 시점과 달라졌으면 저장을 중단하고 `다른 인스턴스 또는 외부 프로그램에서 변경됨` 충돌 대화상자를 표시한다.

## Calibration JSON

Calibration은 데이터셋/sequence 공통 `calibration/calibration.json`을 우선 사용하고, 필요한 경우 `calibration/frames/<frame_id>.json`으로 override한다.

```json
{
  "schema_version": "1.0",
  "reference_frame": "vehicle",
  "lidars": {
    "lidar_top": {
      "T_reference_sensor": [
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 1, 0],
        [0, 0, 0, 1]
      ]
    }
  },
  "cameras": {
    "camera_front": {
      "intrinsic": [[1000, 0, 960], [0, 1000, 540], [0, 0, 1]],
      "T_camera_reference": [
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 1, 0],
        [0, 0, 0, 1]
      ],
      "image_size": [1920, 1080]
    }
  }
}
```

외부 JSON의 `T_reference_sensor`는 로드 시 실제 sensor ID가 포함된 `T_<reference>_<sensor>` 내부 이름으로 바꾼다. 상세 검증 형식은 `schemas/calibration.schema.json`을 따른다.

## Calibration Auto/ON/OFF 동작

- `auto`: sensor별 source coordinate frame을 확인한다. 이미 reference frame이면 변환하지 않고, sensor-local이면 유효한 행렬이 있을 때만 적용한다.
- ON: sensor-local LiDAR에만 변환을 적용한다. 이미 reference frame인 점에는 다시 적용하지 않는다.
- OFF: 변환을 적용하지 않는다. 이미 reference frame인 LiDAR끼리는 병합할 수 있지만 sensor-local 데이터는 raw 단독 보기로 제한한다.
- invalid: ON 전환을 거부하고 어떤 sensor/행렬이 잘못되었는지 표시한다.
- 수동 조정값은 원본 calibration을 덮어쓰지 않고 delta 또는 새 파일로 atomic 저장한다.
- 이미 reference frame인 sensor의 수동 조정은 원 extrinsic 재적용이 아니라 identity base 위의 `correction_delta`로 적용한다.

## 저장 안전성

1. 대상 폴더를 생성한다.
2. revision/fingerprint를 비교하여 외부 변경 여부를 확인한다.
3. 동일 디렉터리에 임시 JSON을 쓴다.
4. flush 및 가능한 경우 fsync 후 임시 JSON을 schema로 검증한다.
5. 기존 파일이 있으면 `.bak.tmp`로 복사·검증한 뒤 `os.replace`로 직전 `.bak`을 갱신한다.
6. `os.replace`로 검증된 임시 JSON을 대상 파일로 교체한다.
7. 실패 시 임시 파일을 정리하고 기존 대상 파일을 유지한다.
