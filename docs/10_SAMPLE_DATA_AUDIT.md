# 전달 샘플 데이터 1차 검사

검사 대상:

```text
local_data/incoming/
  segment-175830748773502782_1580_000_1600_000_with_camera_labels/
```

원본 ZIP과 압축 해제본이 모두 있으며, 분석은 압축 해제본을 읽기 전용으로 사용했다.

## 확인된 구조

- 총 198 frame: `frame_000` ~ `frame_197`
- frame마다 `lidar/`, `camera/`, `labels/`, `metadata.json`
- LiDAR 5대: `TOP`, `FRONT`, `REAR`, `SIDE_LEFT`, `SIDE_RIGHT`
- 각 LiDAR에 `return1`, `return2`
- 카메라 5대: `FRONT`, `FRONT_LEFT`, `FRONT_RIGHT`, `SIDE_LEFT`, `SIDE_RIGHT`
- 총 `.bin` 1,980개, `.jpg` 990개
- 198개 frame 모두 LiDAR BIN 10개와 camera JPG 5개가 일관되게 존재
- segment 공통 calibration은 `segment.json`에 있음
- frame별 vehicle pose와 timestamp는 `frame_xxx/metadata.json`에 있음

## Point cloud 계약

기존 초안의 Nx4가 아니라 이 샘플은 다음 형식이다.

```text
little-endian float32 Nx6
[x, y, z, intensity, elongation, nlz_flag]
```

`schema.json`은 좌표가 이미 `Waymo vehicle frame; x forward, y left, z up`이라고 명시한다. 따라서 LiDAR extrinsic을 다시 적용하면 안 된다.

1,980개 BIN 모두 파일 크기가 Nx6 float32의 한 점 크기인 24 byte로 정확히 나누어진다.

frame 000의 `TOP_return1.bin` 검사 결과:

- shape: `[152078, 6]`
- x 범위: 약 -73.479 ~ 75.610 m
- y 범위: 약 -53.386 ~ 70.569 m
- z 범위: 약 -1.665 ~ 5.219 m
- intensity: 약 0.00025 ~ 11328

intensity가 0~1 범위를 크게 벗어나므로 단순 min/max보다 percentile clipping 또는 log/robust 정규화를 검토해야 한다.

## 기존 라벨

frame마다 다음 source label이 있다.

- `laser_labels.json`: vehicle frame 3D box
- `camera_labels.json`: camera별 원본 2D box
- `projected_lidar_labels.json`: camera별 projected LiDAR 2D box

frame 000에는 3D laser object가 51개 있다. ID는 정수가 아니라 문자열이며 `TYPE_SIGN`도 포함되므로 문자열 ID 보존과 `Sign` class 지원이 필요하다.

## Calibration 해석

- `segment.json`에 5개 LiDAR와 5개 camera calibration이 있다.
- LiDAR point BIN은 이미 vehicle frame이므로 LiDAR extrinsic 적용은 `Not required` 상태이다.
- camera projection을 위해 camera extrinsic 방향을 adapter에서 명시적으로 변환해야 한다.
- camera metadata에는 pose timestamp, trigger time, readout 완료 시각, velocity가 있어 시간 차이와 rolling shutter를 후속 검토할 수 있다.

## 구현에 반영할 결론

1. Nx4 하드코딩을 제거하고 manifest/schema 기반 column contract를 사용한다.
2. `.png`뿐 아니라 `.jpg/.jpeg`를 지원한다.
3. frame 중심 샘플은 `FrameCentricWaymoAdapter`로 그대로 읽는다.
4. 정식 운영 입력은 device 중심 adapter를 사용한다.
5. calibration은 sensor별 `Not required/Applied/Missing/Invalid/Disabled` 상태로 관리한다.
6. source 3D/2D/projected label을 먼저 표시하고 편집 결과는 별도 작업 라벨에 저장한다.
7. source 문자열 ID와 알 수 없는 metadata를 가능한 한 보존한다.
