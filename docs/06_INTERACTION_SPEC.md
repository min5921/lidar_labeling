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
| Shift+W/A/S/D | 선택 box 미세 이동 |
| Q / E | 선택 box yaw 감소 / 증가 |
| R / F | length 증가 / 감소 |
| T / G | width 증가 / 감소 |
| Y / H | height 증가 / 감소 |
| Ctrl+Z / Ctrl+Y | 현재 frame의 undo / redo |

단축키는 설정 가능한 step 값을 사용하며 텍스트 입력 focus에서는 비활성화한다.

## 프레임 이동과 저장

1. 현재 session이 dirty이고 자동 저장이 켜져 있으면 저장한다.
2. 저장 성공 후에만 다음 프레임을 연다.
3. 실패하면 현재 프레임에 남고 사용자에게 원인과 경로를 표시한다.
4. 새 프레임을 로드한 뒤 기존 라벨과 object ID를 복원한다.
5. frame별 undo stack은 분리하며 화면에 없는 frame을 undo하지 않는다.
6. 순차적으로 다음 프레임을 열 때 옵션이 켜져 있으면 도구에서 생성한 객체만 같은 ID로 이어받는다. 원본 import 객체는 자동 복제하지 않는다.
7. Object Detail 3D 카메라 pose는 프레임 전환과 편집에서 유지하고 새 객체 생성 때만 기본 pose로 초기화한다.
