# LiDAR & Camera 3D Bounding Box Label Tool

Python 기반 LiDAR/카메라 3D 바운딩 박스 라벨링 도구이다. 확정된 데이터 계약을 기준으로 core, 샘플 adapter, 1차 편집 GUI를 구현하고 있다.

## 현재 상태

- 요구사항 정규화 완료
- 프로젝트 폴더 뼈대 생성 완료
- 기본 클래스 설정과 라벨 JSON Schema 초안 작성
- Windows 배포 및 깨끗한 PC 검증 계획 작성
- 여러 LiDAR의 calibration 적용·수동 조정·ON/OFF 설계 반영
- 기존 3D/2D 라벨 import·표시·편집·안전 저장 workflow 반영
- 구현 전 충돌 위험 Gate와 사용자 안전·복구 UX 검수 완료
- 1차 core와 현재 샘플용 편집 GUI 구현 완료
- calibration 기반 camera live 3D box projection 구현 완료
- device 중심 번호형 BIN 입력과 sync index adapter 구현 완료
- 운영 입력을 frame당 단일 `MERGED` BIN/PCD로 단순화하고 전체 198 frame 변환 완료
- 선택 박스 중심/yaw 정렬 Object Detail 3D 구현 완료
- 센서/return 단위 프레임 로드 오류 격리와 상태 표시 구현 완료
- 선택 박스 BEV 드래그 이동과 단일 Undo 편집 구현 완료
- BEV 모서리 resize·yaw rotate handle과 SideView z·height handle 구현 완료
- 카메라/객체 편집 패널 경량 분리와 카메라 픽셀맵 캐시 구현 완료
- 내부 `FrameLabel` JSON exporter protocol·registry 확장점 구현 완료
- 비정상 종료 복구 snapshot과 dataset session lock 구현 완료
- CenterPoint 중간 JSON CLI export와 Windows portable 빌드 스크립트 추가
- 전체 프레임 dataset preflight, GUI QA 요약, source/working label 통계 CLI 추가
- export class/finite/box 크기 선검증과 다중 frame 사전 검증 추가

확정된 구현 기본값은 `docs/04_OPEN_DECISIONS.md`에 있다.

## 문서 읽는 순서

1. `docs/01_PRODUCT_SPEC.md`
2. `docs/02_ARCHITECTURE.md`
3. `docs/03_DATA_CONTRACTS.md`
4. `docs/04_OPEN_DECISIONS.md`
5. `docs/05_IMPLEMENTATION_PLAN.md`
6. `docs/06_INTERACTION_SPEC.md`
7. `docs/07_PROJECT_REVIEW.md`
8. `docs/08_DISTRIBUTION_PLAN.md`
9. `docs/09_CALIBRATION_PLAN.md`
10. `docs/10_SAMPLE_DATA_AUDIT.md`
11. `docs/11_DEVICE_CENTRIC_INPUT.md`
12. `docs/12_EXISTING_LABEL_WORKFLOW.md`
13. `docs/13_PRE_IMPLEMENTATION_AUDIT.md`
14. `docs/14_UX_SAFETY_SPEC.md`
15. `docs/15_IMPLEMENTATION_STATUS.md`
16. `docs/16_IMPLEMENTATION_REVIEW.md`
17. `docs/17_WINDOWS_PORTABLE_BUILD.md`
18. `docs/18_PREFLIGHT_AND_QA.md`
19. `docs/19_TRIAL_RUN_MANUAL.md`
20. `docs/20_ONE_CHIP_CONVERSION_MANUAL.md`
21. `docs/21_COMMIT_UPDATE_LOG.md`

실제 실행과 조작은 [`docs/USER_MANUAL.md`](docs/USER_MANUAL.md)를 따른다. 실제 데이터로 써보고
피드백을 남길 때는 [`docs/19_TRIAL_RUN_MANUAL.md`](docs/19_TRIAL_RUN_MANUAL.md)를 순서대로
따라가면 된다.

## 프로젝트 구조

```text
Labelling_tool/
├─ AGENTS.md                    # 협업 및 개발 규칙
├─ README.md
├─ configs/
│  └─ default.json             # 클래스, 기본 크기, 편집/표시 기본값
├─ schemas/
│  ├─ calibration.schema.json  # 멀티 센서 보정 형식 검증
│  ├─ config.schema.json       # 사용자 설정 형식 검증
│  ├─ dataset.schema.json      # device 중심 dataset manifest
│  └─ label.schema.json        # 저장 라벨 형식 검증
├─ docs/                       # 요구사항, 구조, 데이터 계약, 구현 계획
├─ local_data/incoming/        # Git 제외: 전달받은 원본 샘플을 그대로 두는 곳
├─ packaging/                  # 배포 설정과 설치 패키지 자료
├─ src/lidar_label_tool/
│  ├─ app/                     # 시작점, 설정, 의존성 조립
│  ├─ calibration/             # 멀티 센서 보정 적용·검증·수동 조정
│  ├─ domain/                  # Box3D, LabeledObject, FrameLabel
│  ├─ geometry/                # 코너, 변환, 투영
│  ├─ io/
│  │  ├─ adapters/             # frame/device 중심 구조를 FrameBundle로 변환
│  │  └─ loaders/              # BIN/이미지/보정 및 향후 포맷 loader
│  ├─ services/                # 프레임 이동, 편집, 저장 use case
│  ├─ workers/                 # 취소 가능한 scan/load/export background 작업
│  ├─ ui/
│  │  └─ views/                # 3D, BEV, 측면, 이미지 뷰
│  └─ exporters/               # KITTI/OpenPCDet 등 후속 출력
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  └─ fixtures/
├─ resources/icons/
└─ scripts/                    # 개발/검증 보조 스크립트
```

`dataset/`은 저장소 안에 넣는 고정 폴더가 아니라 실행 시 사용자가 선택하는 외부 데이터 루트이다.

첫 배포 목표는 Windows 10/11 x64에서 Python 설치 없이 실행되는 portable 폴더/ZIP이다. 기능이 안정화되면 같은 산출물을 설치형 EXE로 감싼다. 자세한 내용은 `docs/08_DISTRIBUTION_PLAN.md`를 따른다.

## 샘플 데이터 전달 위치

준비한 데이터는 구조와 파일명을 바꾸지 말고 아래에 데이터셋 이름별로 넣는다.

```text
C:\Users\USER\Desktop\Labelling_tool\local_data\incoming\<dataset_name>\
```

이 위치는 Git에서 제외된다. 실제 구조를 검사한 뒤 정식 loader 계약과 최소 테스트 fixture를 만든다.

## 개발 실행

현재 프로젝트 전용 가상환경은 `.venv`에 구성되어 있다.

가장 간단한 방법은 `run_gui.bat`을 더블클릭하고 dataset 폴더를 선택하는 것이다.

전체 변환된 merged 샘플은 `run_merged_sample.bat`을 더블클릭하면 바로 열린다.

```powershell
.\.venv\Scripts\python.exe -m lidar_label_tool inspect `
  .\local_data\incoming\segment-175830748773502782_1580_000_1600_000_with_camera_labels `
  --frame frame_000 --sensor TOP --all-returns

.\.venv\Scripts\python.exe -m lidar_label_tool gui `
  .\local_data\incoming\segment-175830748773502782_1580_000_1600_000_with_camera_labels

.\.venv\Scripts\lidar-label-tool.exe preflight `
  .\local_data\incoming\merged_device_full --json

.\.venv\Scripts\lidar-label-tool.exe stats `
  .\local_data\incoming\merged_device_full --working --json
```

테스트:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

현재 GUI는 기존 3D 라벨을 먼저 불러오며, BEV 클릭 추가, 전체 3D 클릭 선택, BEV 이동·크기·yaw handle, SideView z·height handle, 키보드 편집, 신규 박스의 다음 프레임 이어받기, 삭제, Undo/Redo, 자동 저장을 지원한다. 한 LiDAR return이 손상되어도 다른 cloud와 camera/label은 계속 열며 센서별 `Load failed` 상태를 표시한다. 기본 화면은 전체 3D, camera, 선택 객체 중심 Object Detail 3D이며 BEV/side는 필요할 때 여는 보조 뷰다. Object Detail 3D 시점은 새 박스를 만들 때만 초기화되고 일반 편집과 프레임 이동에서는 유지된다. 저장 결과는 원본 `labels/`를 덮어쓰지 않고 데이터셋의 `annotations/lidar_label_tool/<frame>.json`에 기록하며 미저장 변경은 별도 `.recovery`에 보존한다. Camera GT와 source projected layer는 기본 OFF이고, calibration으로 현재 작업 3D box를 계산하는 live projection이 기본 ON이다. Exporter registry는 내부 JSON과 CenterPoint 중간 JSON을 제공하며 정상 저장과 분리되어 CLI에서 명시적으로 실행한다. GUI export 대화상자는 아직 없다.
