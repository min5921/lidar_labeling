# 조작 명세

## 공통 선택 규칙

- 객체 선택은 object ID 하나로 관리한다.
- 선택 객체는 3D, BEV, 측면, 이미지, 객체 목록에서 같은 강조색으로 표시한다.
- 빈 공간을 클릭하면 선택을 해제한다. 단, BEV 생성 모드에서는 새 객체를 만든다.
- 수치 입력 중에는 전역 편집 단축키를 실행하지 않는다.
- 기존 source 3D label도 신규 box와 같은 방식으로 선택·편집하되 저장은 작업 라벨에 한다.

## BEV

- x축은 전방, y축은 좌측이다.
- 명시적 생성 모드에서만 빈 공간 좌클릭-드래그로 새 박스를 생성한다. 짧은 클릭은 설정의 기본 크기로 생성한다.
- 선택 모드의 빈 공간 클릭은 선택만 해제하며 우발적인 box를 만들지 않는다.
- 박스 좌클릭은 선택, 선택 박스 드래그는 x/y 이동이다.
- 네 모서리 handle은 반대 모서리를 고정하여 length/width와 중심을 조정하고 최소 0.05 m를 유지한다.
- 전방축 바깥의 회전 handle 또는 Q/E로 yaw를 변경한다.
- wheel은 zoom이다.
- 우클릭은 삭제/클래스 변경 context menu를 연다.

## 3D 뷰

- 좌클릭으로 3D box를 선택한다. renderer의 기본 picking이 불충분하면 화면에 투영한 box edge와 클릭 거리로 picking을 구현한다.
- BEV와 객체 목록 선택도 항상 동일한 대체 경로로 제공한다.
- 좌 드래그: 카메라 회전
- 중간 또는 우 드래그: pan
- wheel: zoom
- 이 뷰의 1차 목적은 전체 장면과 박스 배치 확인이다.
- 전체 3D 박스 위의 이름표는 `attributes.name`이 있으면 이를 사용하고, 없으면 class와 축약 ID를 사용한다.

## 측면 뷰

- 기본 x-z 뷰이며 toolbar에서 y-z로 전환한다.
- 박스 드래그로 z를 이동한다.
- 위/아래 handle은 반대 면을 고정하여 중심 z와 height를 조절하고 최소 0.05 m를 유지한다.
- 바닥면/중심 위치를 함께 표시하여 z 중심 의미를 혼동하지 않게 한다.

## 이미지 뷰

- camera selector에서 active camera를 바꾸며 한 대씩 표시한다.
- Camera GT 2D는 독립 annotation이므로 LiDAR object ID와 동일하다고 가정하지 않는다.
- LiDAR projected 2D는 `<lidar_object_id>_<camera>` 규칙으로 object 목록 선택과 연결한다.
- 기본값은 현재 3D box live projection ON, source LiDAR projected 2D와 독립 Camera GT 2D OFF이며 색상 legend를 표시한다.
- 보정값이 없으면 이미지만 표시하고 투영 비활성 상태를 알린다.
- 보정값이 유효하면 3D box edge를 투영한다.
- 카메라 뒤쪽 또는 near plane을 교차하는 edge는 잘못된 긴 선이 생기지 않게 clip/제외한다.
- 1차 릴리스에서는 이미지에서 직접 박스를 편집하지 않는다.
- source camera 2D label, source projected LiDAR label, 현재 3D box projection을 서로 다른 layer/색상으로 켜고 끈다.

## 선택 강조

- object 목록에서 선택하면 3D/BEV/side box를 노란색 굵은 선과 중심 marker로 강조한다.
- active camera에 대응 projected box가 있으면 노란색으로 강조한다.
- 대응 projected box가 없으면 잘못된 임의 매칭 대신 명시적 안내를 표시한다.
- `선택 시 모든 뷰에서 자동 이동` 기본값은 ON이며 사용자가 끌 수 있다.

## 포인트 표시

- 색상 모드: sensor, height, intensity, uniform
- intensity는 extreme outlier 영향을 줄이도록 log + 2~98 percentile 정규화를 사용한다.
- point size는 0.5~8.0 px 범위에서 조절한다.
- 표시 설정은 원본 point 값과 저장 라벨을 변경하지 않는다.

## Calibration 패널

- 기본 상태는 `Auto`이며 유효한 calibration 존재 여부로 ON/OFF가 정해진다.
- 사용자는 ON/OFF를 즉시 전환하여 적용 전후를 비교한다.
- sensor별 checkbox로 표시할 LiDAR를 선택한다.
- calibration OFF에서는 transform을 적용하지 않는다. 이미 reference frame인 LiDAR는 병합할 수 있고 sensor-local LiDAR는 raw 단독 보기로 제한한다.
- 조정 모드에서는 target sensor의 x/y/z/roll/pitch/yaw를 수치와 step 버튼으로 바꾼다.
- reset은 마지막 저장값으로 돌아가고 save-as는 조정본을 새 calibration 파일로 저장한다.
- 잘못된 행렬 또는 누락 sensor는 이름과 원인을 표시하며 병합에서 제외한다.

## 수치 패널

- x, y, z, length, width, height, yaw를 편집한다.
- 표시 yaw 단위는 degree를 기본으로 하되 domain/JSON에는 radian으로 저장한다.
- 양수가 아닌 크기, NaN, Inf는 적용하지 않고 필드 오류를 표시한다.
- 값 적용 즉시 모든 뷰가 갱신되고 session이 dirty 상태가 된다.
- 연속 숫자 입력은 하나의 undo transaction으로 묶고 Enter/focus-out에서 확정한다.

## 키보드

| 키 | 동작 |
|---|---|
| ← / → | 이전 / 다음 프레임 |
| Ctrl+S | 현재 라벨 저장 |
| N / Esc | box 생성 모드 시작 / 취소 |
| Delete | 선택 객체 삭제 |
| 1 / 2 / 3 / 4 | Car / Pedestrian / Cyclist / Sign 선택 |
| W / S | 선택 box x 전방 / 후방 이동 |
| A / D | 선택 box y 좌측 / 우측 이동 |
| Space / Ctrl 단독 | 선택 box z 위 / 아래 이동 |
| Shift+W/A/S/D | 선택 box 미세 이동 |
| Q / E | 선택 box yaw 감소 / 증가 |
| R / F | length 증가 / 감소 |
| T / G | width 증가 / 감소 |
| Y / H | height 증가 / 감소 |
| B | 선택 box의 bottom을 footprint 안쪽 포인트 바닥에 맞춤 |
| Ctrl+Z / Ctrl+Y | 현재 frame의 undo / redo |

이동 단축키는 설정 가능한 step 값을 사용하며 텍스트 입력 focus에서는 비활성화한다.
Ctrl 하강은 다른 키와 조합하지 않고 Ctrl만 눌렀다 놓을 때 실행된다. 따라서 Ctrl+S,
Ctrl+Z, Ctrl+Y 등 기존 조합 단축키는 z 위치를 바꾸지 않는다.

## 프레임 이동과 저장

1. 현재 session이 dirty이고 자동 저장이 켜져 있으면 저장한다.
2. 저장 성공 후에만 다음 프레임을 연다.
3. 실패하면 현재 프레임에 남고 사용자에게 원인과 경로를 표시한다.
4. 새 프레임을 로드한 뒤 기존 라벨과 object ID를 복원한다.
5. frame별 undo stack은 분리하며 화면에 없는 frame을 undo하지 않는다.
6. 순차적으로 다음 프레임을 열 때 옵션이 켜져 있으면 도구에서 생성했거나 사용자가 `이전 폴더의 객체 가져오기…`로 가져온 객체를 같은 ID로 이어받는다. 그 밖의 원본 import 객체는 자동 복제하지 않는다.
7. Object Detail 3D 카메라 pose는 프레임 전환과 편집에서 유지하고 새 객체 생성 때만 기본 pose로 초기화한다.
8. 전체 3D와 BEV/측면의 중심·시점·zoom은 저장, 이전/다음 이동, frame 콤보 이동에서 유지한다.
   같은 객체를 선택 복원하거나 이어받을 때는 자동 focus를 실행하지 않는다. 직접 객체를
   선택하거나 `선택 객체로 이동`을 누르면 기존 focus 동작을 사용한다.

## 프레임 간 수동 객체 연결

- 선택 객체를 `연결 기준으로 기억`한 뒤 이전/다음 또는 원하는 frame으로 이동한다.
- `현재 프레임에 같은 ID로 복사`는 기억한 시점의 박스 하나를 추가한다.
- `선택 객체를 기준 ID로 연결`은 현재 선택 박스의 ID만 기준 ID로 바꾸고 위치·크기·yaw·속성을 유지한다.
- 현재 frame에 기준 ID가 이미 있으면 복사/다른 객체 연결을 막는다. 클래스가 다르면 ID 연결을 거부한다.
- dataset/profile/LiDAR/reference frame을 넘는 연결은 금지한다. 같은 frame의 서로 다른 객체를 합치지 않는다.
- 수동 복사와 연결은 현재 frame의 단일 undo 동작이며 일반 저장·복구 경로를 사용한다.
- 기존 source metadata는 보존하고 변경 전 ID와 기준 frame ID를 `object_link_history`에 기록한다.
- 연결 기준은 실행 중 기억한 snapshot이다. 모든 frame의 ID 일괄 변경, 자동 추적·보간은 수행하지 않는다.

## 분할 폴더 간 여러 객체 가져오기

- 이전 폴더의 마지막 프레임을 저장하고 다음 폴더의 첫 프레임을 연다.
- 프레임 패널의 `이전 폴더의 객체 가져오기…`에서 이전 작업 라벨 JSON 하나를 선택한다.
- 미리보기에서 객체들을 선택하고 추가/기존 ID 건너뜀 개수를 확인한 뒤 적용한다.
- dataset/profile ID는 달라도 되지만 LiDAR ID, reference frame, 좌표·단위·yaw 계약은 같아야 한다.
- 객체 ID·class·box·attributes·source·unknown field를 보존한다. 현재 frame에 같은 ID가 있으면
  기존 박스를 유지하며 덮어쓰거나 자동 ID 연결하지 않는다. 대상에 없는 class는 선택 해제해야 한다.
- 현재 frame의 identity, point/image 경로, revision과 provenance를 이전 것으로 교체하지 않는다.
- 파일 선택 취소, 손상 파일, 미리보기 이후 source 파일/현재 frame 변경은 현재 라벨을 수정하지 않는다.
- 한 번의 Undo로 전체 가져오기를 되돌린다. Ctrl+S와 기존 원자 저장·복구 경로를 사용한다.
- 가져온 객체는 `만든/가져온 박스 다음 프레임으로 이어가기`가 켜져 있으면 다음 프레임으로
  이어진다. 위치 예측이나 좌표 변환은 없으므로 현재 포인트에 맞춰 직접 조정한다.
