# 멀티 LiDAR 및 카메라 Calibration 계획

> D25 변경: 운영 라벨링 GUI는 frame당 사전 보정·병합된 MERGED LiDAR 한 개만 입력받는다. 아래 LiDAR별 적용·조정 절차는 원본→MERGED 전처리/검증 도구의 책임으로 이동한다. GUI 런타임에서는 camera projection calibration만 사용한다.

## 1차 목표

1차 버전은 calibration 값을 자동으로 추정하는 도구가 아니라, 전달된 calibration을 안전하게 읽고 검증·적용하며 사람이 미세조정할 수 있는 도구이다.

- 여러 LiDAR의 extrinsic을 reference frame에 적용
- 활성 LiDAR 포인트를 sensor별 색상 또는 intensity로 표시
- calibration ON/OFF 비교
- x/y/z/roll/pitch/yaw 수동 미세조정
- 원본값 reset, 변경 preview, atomic save
- camera intrinsic/extrinsic이 있으면 box 투영
- calibration이 없으면 reference-frame LiDAR 또는 primary raw LiDAR로 라벨링 유지

ICP, calibration target, feature matching 등으로 행렬을 자동 추정하는 기능은 데이터 특성 확인 후 별도 단계로 설계한다.

## 모드

### Auto

각 sensor의 source coordinate frame을 확인한다. 이미 reference frame이면 `Not required`, sensor-local이고 유효한 행렬이 있으면 `Applied`, 행렬이 없으면 `Missing`으로 판정한다. 수동 correction delta가 활성화되면 `Adjusted`로 표시한다.

### ON

- sensor-local인 활성 sensor에만 `T_reference_sensor`를 적용한다.
- 이미 reference frame인 점에는 extrinsic을 다시 적용하지 않는다.
- 변환된 LiDAR들을 reference frame에서 병합 표시한다.
- 모든 3D box는 reference frame에 생성한다.
- 유효한 camera calibration이 있으면 이미지 투영을 켤 수 있다.

### OFF

- transform을 적용하지 않는다.
- 이미 reference frame이라고 선언된 LiDAR는 그대로 병합할 수 있다.
- sensor-local LiDAR는 primary/raw 단독 보기로 제한하고 서로 겹치지 않는다.
- camera 투영을 비활성화한다.
- UI에 `Calibration OFF` 상태를 분명히 표시한다.
- sensor별 상태를 `Not required / Applied / Missing / Invalid / Disabled`로 표시한다.
- LiDAR transform 상태와 camera projection 사용 여부를 별도 badge/toggle로 표시한다.

## 수동 Calibration 화면

- reference sensor 선택
- 조정할 target LiDAR/camera 선택
- sensor별 표시 checkbox와 색상
- ON/OFF 또는 before/after 즉시 비교
- translation: x, y, z meter 입력과 step 버튼
- rotation: roll, pitch, yaw degree 입력과 step 버튼
- reset, apply, save-as 버튼
- 현재 변환 행렬과 source/target frame 이름 표시
- 변경 여부와 저장 대상 경로 표시
- annotation dirty와 별도의 calibration dirty 표시

수동 delta는 회전/이동 합성 순서가 결과에 영향을 주므로 UI와 코드에서 하나의 규칙으로 고정한다. 기본안은 target/reference frame에서 translation을 적용하고, 센서 원점 기준 local rotation delta를 적용하는 방식이다. 실제 샘플로 조작 감각을 확인한 뒤 문구와 축 gizmo를 확정한다.

effective transform은 `T_effective = correction_delta @ T_base`로 계산한다. 이미 reference frame인 점은 `T_base = identity`이며 원래 sensor extrinsic을 다시 적용하지 않는다.

## 파일 우선순위

1. frame별 override `calibration/frames/<frame_id>.json`
2. dataset/sequence 공통 `calibration/calibration.json`
3. calibration 없음

수동 저장은 원본 입력 파일을 바로 덮어쓰지 않는다. 기본 출력은 별도 `calibration/calibration.adjusted.json`이며 사용자가 명시적으로 채택한 뒤 active calibration으로 지정한다.

## 행렬 검증

- shape 4x4 및 모든 값 finite
- 마지막 행이 `[0, 0, 0, 1]`에 가까운지 확인
- rotation이 orthonormal이고 determinant가 +1에 가까운지 확인
- translation과 회전값이 설정한 안전 범위를 벗어나면 경고
- sensor ID와 실제 point folder 매칭
- inverse 및 transform chain round-trip 수치 테스트
- camera intrinsic shape, focal length 양수, image size 일치

검증 실패 시 해당 sensor는 병합하지 않고 구체적인 오류를 표시한다.

## 시간 동기화 주의

여러 LiDAR의 timestamp가 다르면 정확한 extrinsic만으로 움직이는 객체와 주행 중 배경이 완전히 맞지 않을 수 있다. 샘플에서 sensor별 timestamp를 확인하고 차이가 의미 있으면 다음을 구분한다.

- spatial calibration: 센서 장착 위치와 방향
- temporal calibration: sensor clock offset
- motion compensation: vehicle pose를 이용한 시각 보정

1차에는 `time_offset_ns`를 읽고 표시할 수 있게 하되 motion compensation 구현 여부는 데이터와 pose 제공 여부를 확인한 후 결정한다.

## 완료 기준

- identity 및 알려진 rigid transform 합성 테스트 통과
- ON 상태에서 동일 물체의 LiDAR 포인트가 공통 reference에서 정렬됨
- OFF 상태에서 reference-frame LiDAR만 병합되고 sensor-local LiDAR는 raw 단독 보기로 제한됨
- 잘못된 행렬을 거부하고 앱은 계속 동작함
- 수동 6DoF 변경이 즉시 preview되고 저장/재로드 후 동일함
- calibration 없는 데이터셋도 라벨 생성·저장 가능
- camera projection은 실제 이미지에서 방향과 edge가 시각 검증됨
- calibration fingerprint가 달라진 기존 작업 라벨에는 경고가 표시됨
