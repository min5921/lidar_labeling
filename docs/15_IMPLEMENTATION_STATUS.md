# 1차 구현 상태

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
- dataset folder picker, `run_gui.bat`, 한국어 사용자 매뉴얼
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
- Object Detail 3D 사용자 시점 유지, 신규 박스에서만 초기화
- W/A/S/D 위치, R/F·T/G·Y/H 크기, 좌우 방향키 프레임 단축키
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
- Windows PyInstaller one-folder 빌드 스크립트와 clean-PC 검증 문서
- 전체 frame/센서 파일·라벨·보정·작업 상태의 구조화된 preflight report
- CLI preflight 종료 코드 0/1/2와 GUI 한국어 QA 요약
- source/working 분리 label stats와 recovery 수 집계
- export ID/class/finite/양수 크기 선검증과 batch 전체 사전 검증
- 공유 LRU 렌더 캐시와 객체 선택/박스 표시/측면 평면별 렌더 무효화 분리
- 상태 표시줄의 로드·표시 포인트, 객체, dirty, 경고, 활성 센서 요약
- 키보드 이동·미세 이동·크기·yaw 간격의 실행 중 UI 조절

## 현재 샘플 검증 결과

- 198 frames
- LiDAR: TOP/FRONT/REAR/SIDE_LEFT/SIDE_RIGHT, 각 2 returns
- camera 5대
- frame 000 총 181,852 points
- 기존 3D object 51개: Car 31, Pedestrian 3, Sign 17
- source frame: vehicle, LiDAR calibration 재적용 불필요

## 테스트

- unit/integration/schema 90개
- 원본 source label hash 비변경
- working label revision 1→2와 `.bak` 복구
- stale revision 저장 충돌 거부
- 실제 Windows OpenGL에서 frame 000 렌더링 및 screenshot 저장

## 다음 구현

1. 저장 직전 source fingerprint 재검사
2. LiDAR calibration ON/OFF·수동 6DoF panel
3. frame reviewed/skipped workflow와 다음 미검토 frame 이동
4. portable Windows 배포본 생성, 코드 서명과 clean-PC 최종 검증
