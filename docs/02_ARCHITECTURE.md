# 아키텍처

현재 `codex/v2` 소스 기준의 책임 지도다. 입력·좌표·identity의 규범은
[v2 계약](32_GENERIC_DATASET_V2_CONTRACT.md)을 우선한다. 기능별 검토 결과와 후속 정리는
[프로젝트 검토·유지보수](35_PROJECT_REVIEW_AND_MAINTENANCE.md)를 참고한다.

## 의존 방향

```text
ui/views ──> services ──> domain
    │             │          ▲
    │             ├──> io ───┘
    │             └──> calibration
    └──> geometry <─────┘

app: 위 구성요소를 조립하고 실행
exporters: domain을 외부 포맷으로 변환
```

`domain`은 가장 안쪽 계층이며 GUI 및 파일 라이브러리를 import하지 않는다. `io`는 외부 파일을 domain 객체로 바꾸고, `calibration`은 센서 변환을 검증·적용한다. `services`는 로드·편집·저장 흐름과 현재 세션 상태를 관리한다. `ui`는 사용자 입력을 service 명령으로 전달하고 상태를 렌더링한다.

## 폴더별 책임

### `app/`

- 애플리케이션 진입점
- 설정 로드 및 검증
- 로거와 예외 처리
- loader, repository, service, window 조립
- 개발 실행과 frozen 배포 환경 모두에서 resource 경로 해석
- 사용자 설정과 로그의 OS별 쓰기 가능 경로 관리

### `domain/`

- `Box3D`
- `LabeledObject`
- `FrameLabel`
- 값 범위 검증 및 JSON dictionary 변환
- GUI 프레임워크에 의존하지 않는 범용 데이터셋 v2 manifest, profile, frame-index 값 객체

### `geometry/`

- 8개 박스 코너 계산
- z축 yaw 회전
- BEV/측면 폴리곤
- 좌표 변환과 카메라 투영

### `calibration/`, `calibration_editor/`

- `calibration/waymo_camera.py`: camera 보정 해석과 projection
- `calibration_editor/`: GUI 비의존 보정 모델·투영·저장과 reference box 읽기
- `ui/calibration_editor/`: 수동 6DoF/intrinsic 편집 화면
- `geometry/transforms.py`: `T_target_source` 검증과 좌표 변환
- v2 LiDAR는 label-ready 단일 cloud이며 여기서 여러 LiDAR를 자동 병합하지 않음

### `io/loaders/`, `io/labels/`

- manifest/schema 기반 float32 NxC BIN 및 PCD ASCII/binary loader
- JSON label repository와 원자적 저장, v1/v2 repository 명시적 분기
- source label importer와 working label repository 분리
- 명시적 객체 가져오기의 source schema·fingerprint 검사

이미지 로드와 프레임 조합은 `workers/frame_loader.py`, 데이터셋 스캔과 파일 경로 해석은
adapter가 담당한다. 모든 I/O가 point loader 안에 있는 것은 아니다.

### `io/dataset_v2.py`, `io/json_schema.py`

- `dataset.json` 헤더를 먼저 읽어 v1과 v2를 명시적으로 구분
- Draft 2020-12 JSON Schema로 manifest, frame index, taxonomy 구조 검증
- 검증된 JSON을 immutable v2 domain 객체로 변환
- 개발 소스, 설치 package, frozen 실행에서 동일한 schema resource를 해석

### `io/adapters/`

- `DeviceCentricV2Adapter`: 범용 v2의 선택 profile, frozen index, 단일 LiDAR 입력
- `DeviceCentricAdapter`: v1 호환 sensor/device 중심 입력
- `WaymoFrameCentricAdapter`: Waymo frame 중심 호환 입력
- 물리적 파일 배치를 공통 `FrameBundle`로 변환
- v2 런타임은 확정 index만 읽음; nearest 계산은 구성·재동기화 서비스의 책임
- source coordinate frame과 포인트 column 계약 전달

### `services/`

- 현재 프레임/선택 객체/dirty 상태
- 객체 추가, 삭제, 이동, 크기, 회전, 클래스 변경
- `AnnotationHistory`의 undo/redo 및 dirty 기준
- 프레임 이동 전 저장 정책
- calibration ON/OFF와 활성 LiDAR 상태
- source frame data와 working label을 `FrameBundle`로 조합
- 범용 v2의 sensor/profile 참조, hash, 경로 경계, frame binding을 읽기 전용으로 검증
- dataset 구성/profile 추가/재동기화 generation transaction
- 객체 수동 연결·폴더 간 이관·선택 객체 1-step 추적 보조
- profile 선택 정보·라벨 통계·명시적 export

v2 구성·동기화·저장은 UI가 JSON을 직접 쓰지 않고 service 계층의 transaction을 통해 수행한다.
생성 transaction과 runtime adapter까지 구현되어 있다. 기존 v1 adapter와 one_chip 변환기는
호환 계층으로 유지한다. 계약에 정의된 전체-frame v1→v2 migrator는 아직 구현된 것으로
간주하지 않는다.

### `workers/`

- `frame_loader.py`의 frame/cloud/image 로드와 선택 객체 추적
- 구성·export 등 장시간 GUI 작업은 별도 worker에서 service 실행
- request generation과 cancel token
- worker 결과를 immutable data로 main thread에 전달
- Qt widget과 OpenGL item에는 직접 접근하지 않음

### `ui/views/`

- 3D 포인트와 wireframe box 렌더링
- BEV 생성/선택/드래그
- 측면 z/height 편집
- 이미지와 선택적 투영
- object/frame/parameter panel
- calibration panel과 before/after overlay

## 현재 핵심 호출 계약

- BIN/PCD loader: `can_load(path, spec) -> bool`
- BIN/PCD loader: `load(path, spec, *, sensor_id, return_id) -> PointCloudData`
- repository: `load(frame_id) -> FrameLabel`
- repository: `save(frame_label) -> FrameLabel` (성공 revision 반영)
- importer: `import_laser_labels(source_frame) -> FrameLabel`
- `LabelExporter.validate(frame_label) -> None`
- `LabelExporter.export_frame(frame_label, output_path) -> None`
- `DatasetAdapter.scan() -> DatasetIndex`
- `DatasetAdapter.load_source_frame(frame_id) -> SourceFrameData`
- `FrameSessionService.open_frame(frame_id) -> OpenedFrame`

`DatasetAdapter`와 `LabelExporter`는 Protocol이다. loader/repository/importer의 위 표기는
현재 구현의 호출 형태이며 모두 별도의 Protocol 클래스로 선언되었다는 뜻은 아니다.
새 포맷은 해당 경계에서 추가하여 UI가 포맷별 파일 구조를 해석하지 않게 한다.

`PointCloudSpec`에는 dtype, byte order, column 이름, source coordinate frame이 포함된다. loader가 파일명만 보고 column 수나 좌표 frame을 추측해서는 안 된다.

`PointCloudData`는 UI에 raw NxC 배열을 노출하지 않고 `xyz: float32[N,3]`, 이름별 attribute 배열, sensor/return/source-frame metadata를 가진다. intensity가 몇 번째 column인지 또는 아예 없는지는 loader만 안다.

## 실행 경로와 사용자 파일

- dataset과 label은 사용자가 선택한 외부 경로에 둔다.
- bundle에 포함된 `configs/default.json`, schema, icon은 읽기 전용 resource이다.
- 사용자 override 설정과 로그는 `app/runtime_paths.py`가 정하는 Windows AppData/Linux XDG
  사용자 쓰기 가능 경로를 사용한다.
- 현재 작업 디렉터리나 개발 저장소 상대 경로에 의존하지 않는다.
- 개발 실행과 배포 실행에서 동일한 resource resolver API를 사용한다.

## 상태 동기화

현재 `MainWindow`가 활성 frame과 선택 ID, `AnnotationHistory`가 현재 label·undo/redo·dirty
기준을 소유한다. `FrameSessionService`는 source와 working label을 조합한다. view의 박스는
렌더링/제스처용 snapshot이며 편집 결과는 공통 label 상태로 되돌아와 모든 view에 반영된다.
프레임 요청 시 view의 진행 중 gesture를 취소하고 로드 중 편집을 잠근다. 오래된 worker 결과는
request generation으로 버린다. 단일 `AnnotationSession` 클래스로 통합된 상태는 아니다.
