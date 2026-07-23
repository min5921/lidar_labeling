# 구현 및 검증 계획

각 단계는 앞 단계의 테스트가 통과한 뒤 진행한다.

## Phase 0 — 계약과 개발 기반

- 확정 계약과 P0 위험 Gate 재확인
- Python/가상환경과 Windows OpenGL 동작 확인
- `pyproject.toml`과 의존성 버전 고정
- config 및 label JSON Schema 검증
- 실제 멀티 LiDAR 폴더, timestamp, calibration 형식 조사
- background worker/request generation 및 session lock 설계
- dataset-open validation summary와 writable workspace 선택
- lint/type/test 실행 명령 구성

완료 기준: 잘못된 config/label 예제가 예측 가능한 오류를 낸다.

배포 관점 확인: 간단한 PySide6/OpenGL 창을 standalone으로 묶어 Python 미설치 테스트 환경에서 실행한다. 이를 통해 패키징 불가능한 renderer 선택을 초기에 피한다.

## Phase 1 — 도메인과 geometry

- `Box3D`, `LabeledObject`, `FrameLabel`
- JSON dict 직렬화/역직렬화
- yaw 정규화, 8 corners, BEV/측면 폴리곤
- rigid transform, inverse, chain, roll/pitch/yaw delta 합성
- calibration model과 행렬 수치 검증
- 입력값 검증

완료 기준: 알려진 축 정렬/회전 박스의 코너와 round-trip 테스트가 통과한다.

## Phase 2 — 데이터 I/O

- 데이터셋 스캔과 frame 매칭
- manifest 기반 BIN/JPG/PNG/선택적 calibration 로드
- sensor별 frame 매칭과 primary LiDAR 선택
- dataset/sequence calibration과 frame override 우선순위
- JSON label repository
- Waymo-style laser/camera/projected label importer
- 작업 라벨 우선 로드와 source label fallback
- 원자적 저장과 실패 복구
- source fingerprint/revision 기반 충돌 감지

완료 기준: 정상/누락/손상 fixture 통합 테스트가 통과한다.

## Phase 3 — 읽기 전용 GUI

- 메인 창과 splitter 레이아웃
- 3D, BEV, 측면, 이미지 표시
- active camera selector와 camera별 image/label 전환
- sensor별 색상/표시 toggle과 calibration ON/OFF
- reference frame 변환 및 활성 LiDAR 병합 표시
- 이전/다음 프레임과 포인트 다운샘플
- background load, progress/cancel, stale-result 폐기
- 객체 목록 및 기존 박스 표시
- source 3D/2D/projected label layer toggle
- 3D box screen-space picking prototype

완료 기준: 샘플 데이터셋을 열고 여러 프레임을 안정적으로 탐색한다.

## Phase 4 — 편집 GUI

- 추가, 선택, 이동, 크기, yaw, z/height 편집
- 수치 패널과 클래스 변경
- 모든 뷰의 단일 선택 상태 동기화
- 삭제와 단축키
- undo/redo
- 명시적 create mode와 accidental-edit 방지
- calibration panel의 6DoF 수동 조정, reset, preview, save-as

완료 기준: 마우스/키보드/수치 패널 편집이 동일한 domain 값으로 수렴한다.

## Phase 5 — 저장과 세션 안전성

- save, autosave, dirty 표시
- 주기적 recovery snapshot과 재시작 복구 안내
- dataset session lock과 외부 변경 충돌 대화상자
- frame 상태(unvisited/in_progress/reviewed/skipped)와 진행률
- 종료/프레임 이동 실패 처리
- 빈 프레임 저장
- source label 비덮어쓰기와 working label round-trip
- 별도 destination의 source-compatible export
- 최근 데이터셋 경로 등 비라벨 사용자 설정

완료 기준: 강제 실패 테스트에서도 기존 JSON이 보존되고 재실행 시 값이 복원된다.

## Phase 6 — 카메라 투영과 마감

- 보정 검증 및 3D 코너/edge 투영
- calibration 상태/행렬 방향/시간 offset 진단 표시
- calibration fingerprint 변경 경고
- 카메라 뒤 점, near-plane, 화면 밖 edge 처리
- 사용자 오류 메시지와 로그
- 설치/실행/포맷/단축키/제약 README

완료 기준: 알려진 합성 calibration과 실제 샘플 양쪽에서 투영 방향을 시각 검증한다.

## Phase 7 — 실험실 소스 운영

- Windows/Linux Python 3.10+ setup/run script
- runtime/development dependency lock
- source 환경과 기본 설정 자동 검증
- Windows Server 2022와 Ubuntu 22.04 CI
- 한글/공백 경로와 외부 데이터셋 smoke test

완료 기준: 새 실험실 PC에서 setup 후 앱이 실행되고, 외부 데이터셋을 열어 라벨 생성·저장·재로드까지 성공한다.

## 이후 확장

- PCD/NPY/CSV loader
- KITTI/OpenPCDet exporter
- 멀티 카메라 동시 mosaic
- 프레임 보간/트래킹
- 플러그인형 데이터셋 adapter
