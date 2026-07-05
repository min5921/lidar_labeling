# 아키텍처

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

### `geometry/`

- 8개 박스 코너 계산
- z축 yaw 회전
- BEV/측면 폴리곤
- 좌표 변환과 카메라 투영

### `calibration/`

- sensor calibration domain model
- `T_target_source` 4x4 행렬 검증과 적용
- LiDAR → reference, reference → camera 변환 chain
- 수동 x/y/z/roll/pitch/yaw delta 합성
- calibration session의 apply/preview/reset/save
- 센서별 활성화와 정렬 확인용 색상 구분

### `io/loaders/`

- 공통 point-cloud loader 프로토콜
- manifest/schema 기반 float32 NxN BIN loader
- 이미지 loader
- 보정 loader
- 데이터셋 스캔 및 프레임 매칭
- JSON label repository와 원자적 저장
- source label importer와 working label repository 분리

### `io/adapters/`

- `DeviceCentricAdapter`: 정식 sensor/device 중심 입력
- `FrameCentricWaymoAdapter`: 현재 전달된 frame 중심 자료
- 물리적 파일 배치를 공통 `FrameBundle`로 변환
- manifest, frame ID, timestamp 기반 동기화
- source coordinate frame과 포인트 column 계약 전달

### `services/`

- 현재 프레임/선택 객체/dirty 상태
- 객체 추가, 삭제, 이동, 크기, 회전, 클래스 변경
- undo/redo 명령(1차 후반 단계)
- 프레임 이동 전 저장 정책
- calibration ON/OFF와 활성 LiDAR 상태
- source frame data와 working label을 `FrameBundle`로 조합

### `workers/`

- dataset scan, frame load, prefetch, export background task
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

## 핵심 인터페이스

- `PointCloudLoader.can_load(path, spec) -> bool`
- `PointCloudLoader.load(path, spec: PointCloudSpec) -> PointCloudData`
- `LabelRepository.load(frame) -> FrameLabel`
- `LabelRepository.save(frame_label) -> None`
- `LabelImporter.import_frame(source_frame) -> FrameLabel`
- `LabelExporter.export_frame(frame_label, destination, options) -> ExportReport`
- `CalibrationProvider.load(frame) -> SensorCalibration | None`
- `CalibrationSession.transform_cloud(cloud: PointCloudData) -> PointCloudData`
- `DatasetAdapter.scan(root) -> DatasetIndex`
- `DatasetAdapter.load_source_frame(frame_id) -> SourceFrameData`
- `FrameSessionService.open_frame(frame_id) -> FrameBundle`

구체 클래스가 아닌 이 인터페이스에 의존하여 새 포맷을 추가할 때 UI 수정이 발생하지 않도록 한다.

`PointCloudSpec`에는 dtype, byte order, column 이름, source coordinate frame이 포함된다. loader가 파일명만 보고 column 수나 좌표 frame을 추측해서는 안 된다.

`PointCloudData`는 UI에 raw NxC 배열을 노출하지 않고 `xyz: float32[N,3]`, 이름별 attribute 배열, sensor/return/source-frame metadata를 가진다. intensity가 몇 번째 column인지 또는 아예 없는지는 loader만 안다.

## 실행 경로와 사용자 파일

- dataset과 label은 사용자가 선택한 외부 경로에 둔다.
- bundle에 포함된 `configs/default.json`, schema, icon은 읽기 전용 resource이다.
- 사용자 override 설정과 로그는 Qt의 표준 application-data 경로를 사용한다.
- 현재 작업 디렉터리나 개발 저장소 상대 경로에 의존하지 않는다.
- 개발 실행과 배포 실행에서 동일한 resource resolver API를 사용한다.

## 상태 동기화

단일 `AnnotationSession`이 현재 프레임, 객체 목록, 선택 ID, dirty 상태를 소유한다. 각 view는 별도 박스 사본을 소유하지 않고 session 변경 신호를 받아 다시 그린다. 이 규칙이 네 뷰 간 값 불일치를 막는다.
