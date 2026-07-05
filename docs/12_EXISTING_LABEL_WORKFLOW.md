# 기존 라벨 표시·수정·저장

## 목표

source label이 있는 frame을 열면 빈 화면에서 시작하지 않고 기존 box를 먼저 표시한다. 사용자는 기존 객체를 선택·이동·크기 조절·회전·클래스 변경·삭제하거나 새 객체를 추가한 뒤 저장한다.

## 로드 우선순위

1. `<annotation_root>/<dataset_id>/annotations/lidar_label_tool/<frame_id>.json` 작업 라벨
2. source `laser_labels.json` import
3. 빈 `FrameLabel`

첫 import 시 source path, source format, 원본 object ID를 provenance로 기록한다. 작업 라벨이 생긴 이후에는 앱 재실행 시 작업 라벨을 우선하여 이전 수정 결과가 사라지지 않게 한다.

작업 라벨 파일이 존재하지만 손상되었거나 schema가 맞지 않으면 source label로 조용히 fallback하지 않는다. `.bak`, recovery snapshot, source 재import를 비교하여 사용자가 선택하게 한다.

## 현재 샘플 layer

- `laser_labels.json`: 편집 가능한 3D box의 최초 source
- `camera_labels.json`: camera별 원본 2D 참고 layer
- `projected_lidar_labels.json`: camera별 projected LiDAR 참고 layer
- 현재 3D box projection: calibration으로 실시간 계산한 layer

2D source label은 1차에 참고용으로 표시하고 직접 편집하지 않는다. 3D laser label은 모든 3D/BEV/side view에서 편집 가능하다.

## ID와 class

- source 문자열 ID를 그대로 보존한다.
- 새 객체는 UUID 문자열 ID를 만든다.
- `TYPE_VEHICLE` → `Car`
- `TYPE_PEDESTRIAN` → `Pedestrian`
- `TYPE_CYCLIST` → `Cyclist`
- `TYPE_SIGN` → `Sign`
- 알 수 없는 type → `Unknown`, 원래 type은 metadata에 보존

## 저장 정책

- source 파일은 절대 자동 overwrite하지 않는다.
- 작업 라벨은 atomic save + 직전 `.bak` 하나를 사용한다.
- source에서 알 수 없는 metadata는 가능한 한 round-trip 보존한다.
- 저장된 작업 라벨에는 provenance와 reference frame을 기록한다.
- 저장된 작업 라벨에는 source와 calibration fingerprint, revision을 기록한다.
- source-compatible JSON이 필요하면 `exports/<format>/...`에 명시적으로 export한다.

## UI 표시

- object list에 source/imported/new/modified 상태 표시
- 수정된 frame에는 dirty 표시
- source 2D, projected 2D, live projection layer checkbox
- 원본과 현재 box 비교 toggle
- 현재 frame의 imported/modified/deleted/added 개수 표시

## 완료 기준

- frame 000의 기존 51개 3D object가 로드·표시된다.
- source 문자열 ID와 `TYPE_SIGN`이 손실되지 않는다.
- 기존 box 수정, 삭제, 신규 추가 후 저장·재로드 결과가 동일하다.
- source JSON의 hash와 내용은 변경되지 않는다.
- 작업 라벨을 별도 Waymo-style output으로 export할 수 있다.
- 손상 working JSON에서 `.bak` 또는 recovery를 선택해 복구할 수 있다.
