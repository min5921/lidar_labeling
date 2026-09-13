# 구현 상태

## 범용 데이터셋 v2 구현 완료 범위

완료:

- 활성 LiDAR별 profile과 label identity 계약
- dataset, frame-index, taxonomy, working-label JSON Schema
- v1/v2를 구분하는 manifest header reader
- GUI/Qt와 독립된 immutable v2 domain model
- schema와 sensor/profile/hash/path/frame binding을 검사하는 읽기 전용 semantic validator
- `validate-v2` CLI와 LiDAR-only, camera 선택, 한글·공백 경로 회귀 테스트
- 폴더 자동 탐색과 `dataset.json` 생성 화면
- timestamp CSV 선택과 deterministic sync index 생성
- v2 runtime adapter와 profile별 working-label repository
- GUI의 profile 선택, progress/cancel, 외부 workspace transaction
- profile/LiDAR identity를 보존하는 recovery와 session lock
- 분석 결과 확인 후 모든 profile을 한 generation으로 교체하는 원자적 재동기화
- 원본 fingerprint 충돌, 취소, 저장 실패 rollback과 이전 generation 보존
- 두 LiDAR·카메라·동일 frame ID·외부 workspace·한글/공백 경로 통합 테스트

GUI에서 `dataset.json`이 없는 폴더를 선택하면 범용 구성 화면으로 연결한다. 기존 v1,
Waymo와 특수 one_chip 입력은 별도 호환 경로로 계속 유지한다.

## 기존 1차 구현

## 완료

- Python package/CLI와 프로젝트 전용 `.venv`
- manifest 기반 `PointCloudSpec`과 canonical `PointCloudData`
- float32 NxC BIN loader, stride 검증, invalid XYZ 격리
- `Box3D`, `LabeledObject`, `FrameLabel`과 JSON round-trip
- 3D corners, BEV/side geometry, rigid transform 검증
- 현재 샘플용 `WaymoFrameCentricAdapter`
- 기존 `laser_labels.json` import와 문자열 ID/unknown source 보존
- camera/projected LiDAR 2D reference layer 로드
- revision 충돌 감지, atomic save, 직전 `.bak`, source 비변경 검증
- request generation 기반 background frame load
- 3D/BEV/side/camera GUI와 단일 object 선택 상태
- 5개 LiDAR toggle, 5개 camera 전환, 3D/2D 기존 라벨 표시
- object 목록 선택 시 3D/BEV/side와 대응 LiDAR projected 2D 강조 및 자동 포커스
- point 색상(sensor/height/intensity/uniform)과 0.5~8 px 크기 조절
- 모든 뷰의 box line width 0.5~8 조절
- 독립 Camera GT와 LiDAR projected layer의 의미/기본 표시 분리
- Windows 실제 OpenGL GUI smoke test
- BEV 클릭 기본 크기 box 생성, 수치 기반 class/center/size/yaw 편집, 삭제
- frame별 undo/redo와 dirty 상태 표시
- Ctrl+S 원자 저장과 frame 이동 시 저장 성공 후 전환
- Waymo camera calibration 기반 현재 작업 3D box live wireframe projection
- 기존 dataset adapter와 작업/source 3D label을 재사용하는 독립 camera–LiDAR calibration 편집기
- 기존 calibration 기준 6DoF·intrinsic 조정, 전/후 point/box preview, 검증 frame 기록
- calibration 편집기의 camera/LiDAR 높이 비율 slider·splitter 동기화
- camera 투영 point 1~30 px 크기 slider와 기본 OFF인 선택적 검정 외곽선 렌더링
- camera 원본 이미지만 검정 배경으로 ON/OFF하고 projection overlay는 유지하는 비교 모드
- frame별 세션 전용 BEV 기준 박스 생성·이동·resize·yaw·수치 편집과 camera 즉시 투영
- calibration 기준 박스의 point floor z 맞춤, 기존 라벨 읽기 전용 유지와 저장 경로 완전 분리
- 원본 calibration 덮어쓰기 금지와 schema 검증·atomic Save As·조정본 `.bak`
- dataset folder picker, `launchers/`의 OS별 실행 파일, 한국어 사용자 매뉴얼
- dataset preflight summary와 실제 작업 경로 쓰기 probe
- 읽기 전용 dataset용 별도 annotation workspace 선택
- camera near-plane/image clipping, undistorted frustum filter, camera-synced box 투영
- 전체 3D + camera + yaw 정렬 Object Detail 3D 기본 레이아웃
- BEV/side 보조 뷰 토글과 생성 시 BEV 자동 표시
- `DeviceCentricAdapter`의 번호형 파일, exact-stem/index sync, LiDAR transform
- 단일 `MERGED` BIN/PCD 운영 입력, PCD ASCII/binary loader, 전체 198 frame 변환기
- 무라벨/빈 객체 frame의 명시적 작업 JSON 생성
- 전체 3D 화면 투영 기반 박스 클릭 선택
- 3D 객체 이름표와 BEV 이름·length×width 표시 토글
- 신규 생성 객체의 순차 다음 프레임 이어받기와 ID 유지
- 같은 LiDAR·좌표계의 분할 폴더 간 저장 객체 일괄 가져오기, 선택 미리보기, 중복 ID 건너뜀
- 가져온 객체의 ID/metadata/이력 보존, 대상 frame identity 유지, 단일 Undo와 이후 순차 이어받기
- 선택 객체의 순차 다음 frame 국소 포인트 추적 보조, x/y·선택적 z만 조정하고 크기·yaw 유지
- 객체 ID별 opt-in 지면 보정과 공중 표지판의 기본 포인트 상대 z 이동, 실패 시 기존 위치 유지
- 추적의 worker/generation/cancel·기존 대상 ID 보호·별도 Undo와 원자 저장 경로
- 전체/상세 3D·BEV·측면에서 선택 박스 내부 포인트 노란색 강조와 원본/렌더 캐시 비변경
- 기준 객체 기억 후 이전/임의 frame에 같은 ID로 수동 복사, 기존 객체 ID 연결과 이력 보존
- 전체 3D/BEV/측면의 저장·이전/다음·콤보 이동 시 시점 유지
- Object Detail 3D 사용자 시점 유지, 신규 박스에서만 초기화
- W/A/S/D x/y 위치, Space/Ctrl 단독 z 위치, R/F·T/G·Y/H 크기, 좌우 방향키 프레임 단축키
- B 단축키로 선택 박스 포인트 바닥 맞춤, 수치 입력/로드 중 실행 차단
- 센서/return별 point cloud 로드 오류 격리와 구조화된 `sensor_errors`
- reference layer별 JSON 오류 격리와 `reference_layer_errors`
- 센서별 Not required/Applied/Missing/Invalid/Disabled/Load failed/Unknown 표시
- MERGED reference cloud 유지 상태에서 보정 없는 선택 raw LiDAR 비활성화
- 카메라 레이어 및 3D 객체 편집 위젯의 경량 panel 분리
- 선택 박스 BEV x/y 드래그 미리보기와 단일 undo transaction
- BEV 네 모서리 length/width resize와 전방축 yaw rotate handle
- SideView 본체 z 이동과 상·하단 height resize handle
- 모든 handle 편집의 0.05 m 최소 크기와 단일 undo transaction
- 동일 camera image 경로의 QPixmap 재사용과 overlay만 갱신
- instance-scoped exporter registry와 atomic 내부 FrameLabel JSON exporter
- dirty frame 주기 복구 snapshot과 복원/무시/삭제 사용자 선택
- PID/hostname 기반 dataset session lock, stale/malformed 교체, 소유권 안전 해제
- `centerpoint_intermediate_json` 명시적 exporter와 단일/다중 frame CLI export
- Windows/Linux source 가상환경 setup과 clean-environment 검증 문서
- 전체 frame/센서 파일·라벨·보정·작업 상태의 구조화된 preflight report
- CLI preflight 종료 코드 0/1/2와 GUI 한국어 QA 요약
- source/working 분리 label stats와 recovery 수 집계
- export ID/class/finite/양수 크기 선검증과 batch 전체 사전 검증
- 공유 LRU 렌더 캐시와 객체 선택/박스 표시/측면 평면별 렌더 무효화 분리
- 상태 표시줄의 로드·표시 포인트, 객체, dirty, 경고, 활성 센서 요약
- 키보드 이동·미세 이동·크기·yaw 간격의 실행 중 UI 조절
- one_chip `header_aligned` nearest sync와 camera 반복/점프 QA report
- 단순 `lidar/`, `cam_left/`, `cam_right/` 출력과 legacy 구조 호환
- 사용자 AppData/XDG 설정·로그 경로
- 재현 가능한 runtime/development dependency lock
- source/calibration fingerprint 변경의 preflight·GUI 경고와 저장 전 재확인
- working label의 알 수 없는 frame/object field round-trip 보존

## 현재 샘플 검증 결과

- 198 frames
- LiDAR: TOP/FRONT/REAR/SIDE_LEFT/SIDE_RIGHT, 각 2 returns
- camera 5대
- frame 000 총 181,852 points
- 기존 3D object 51개: Car 31, Pedestrian 3, Sign 17
- source frame: vehicle, LiDAR calibration 재적용 불필요

## 테스트

- 전체 unit/integration/schema 회귀 테스트 272개 통과 (2026-09-13, 이번 커밋 범위)
- 전체 `src` mypy와 저장소 전체 Ruff 통과
- 두 폴더 간 객체 가져오기·저장/재로드·순차 이어받기, 중복 ID/취소/파일 변경/저장 실패 보호 검증
- 합성 이동·공중 표지판·지면 경사·중복 후보·포인트 누락·취소·추적 오류·Undo·포인트 강조 회귀 검증
- 자동 추적의 실제 주행 데이터 정확도 검수는 별도 운영 Gate이며 학습형 추적기 정확도를 보장하지 않음
- 원본 source label hash 비변경
- working label revision 1→2와 `.bak` 복구
- stale revision 저장 충돌 거부
- 실제 Windows OpenGL에서 frame 000 렌더링 및 screenshot 저장

## 다음 구현

1. 공식 Python 3.12가 설치된 clean Windows PC에서 한글/공백 경로 setup/open/edit/save 최종 인증
2. third-party license 묶음, 앱 아이콘, 버전 정보, 코드 서명
3. frame reviewed/skipped workflow와 다음 미검토 frame 이동
4. source-compatible exporter와 GUI export 대화상자
