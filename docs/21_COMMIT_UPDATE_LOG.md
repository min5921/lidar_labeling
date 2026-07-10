# 커밋별 업데이트 기록

이 문서는 프로젝트 진행 중 어떤 커밋에서 무엇이 추가·수정되었는지 추적하기 위한 기록이다.
배포 관련 변경은 `codex/portable-distribution` 브랜치에서 관리한다.

## bf70370 — feat: add portable one chip distribution workflow

one_chip 변환·동기화·calibration 검증과 Python 무설치 Windows 포터블 배포 workflow를 하나의
배포 브랜치에 정리한 커밋이다.

- one_chip 변환기
  - 기본 `header_aligned` nearest sync와 camera 반복/점프 QA
  - `lidar/`, `cam_left/`, `cam_right/` simple 구조 및 legacy 구조 호환
  - 사용자가 스크립트 상단에서 source/output/calibration 경로를 수정할 수 있는 기본값
- 데이터·라벨 안전성
  - simple manifest와 dataset schema 일치
  - source/calibration fingerprint 변경의 preflight·GUI 경고와 저장 전 확인
  - working JSON의 알 수 없는 frame/object field 보존
- 포터블 실행 안정성
  - PyInstaller `_MEIPASS` resource 경로 고정
  - crash log를 `%LOCALAPPDATA%\LiDARLabelTool\logs`에 기록
  - 반복 빌드의 `-SkipDependencyInstall` 지원
- 재현 가능한 릴리스 패키징
  - `package_windows_release.ps1`로 최상위 EXE, `_internal`, launcher, 매뉴얼, ZIP, SHA-256 생성
  - 최종 로컬 검수본 `LiDARLabelTool_Portable_20260710_r6`
- 문서
  - 배포 체크리스트, 릴리스 매뉴얼, 요구사항 20개 재검수 결과 추가
  - 사용자 매뉴얼의 portable/simple-layout 설명 최신화

검증 결과:

- source venv와 build venv: `111 passed`
- `ruff check .`: 통과
- 로컬 198-frame dataset preflight: errors 0, warnings 0
- r6 EXE와 Start launcher: 정상 실행·종료, crash log 변화 없음, session lock 잔여 없음
- r6 ZIP: `82994162` bytes
- SHA-256: `55477CBF38BC9E3E7B6C57EAE65BF33945213C695DA50DDC86543DFB608336B3`
- 현재 검수 세션에는 `E:` 드라이브가 없어 r6 one_chip 실데이터 재검증은 보류
- Python 미설치 별도 clean Windows PC 최종 인증은 보류

## 검증 기록

2026-07-09 현재 작업트리 기준으로 다음 명령을 실행했다.

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

결과:

- pytest: 99 passed
- ruff: All checks passed
- 참고: pytest cache 쓰기 권한 경고가 1건 있었지만 테스트 실패는 아니다.

실제 변환 데이터 경로 `E:\one_chip_converted`도 확인하려 했지만, 이 검증 세션에서는 `E:` 드라이브가
마운트되어 있지 않았다. 따라서 코드/테스트 검증은 완료했지만, 실제 `frames.jsonl` 및 GUI 입력
데이터 수준의 현장 검증은 `E:` 드라이브가 보이는 환경에서 다시 실행해야 한다.

확인된 실패 상태:

```text
Get-PSDrive -PSProvider FileSystem
→ C:만 표시됨

lidar-label-tool preflight E:\one_chip_converted
→ [error] dataset_root_missing E:\one_chip_converted
```

## 2026-07-09 당시 커밋 전 작업트리

아래 작업은 이후 `697e276` 커밋에 반영됐다.

### one_chip 실제 데이터 변환·검증 지원

- `scripts/convert_one_chip_dataset.py`
  - `E:\one_chip` ROS2 MCAP 데이터를 `device_centric` dataset으로 변환한다.
  - LiDAR PointCloud2를 `MERGED` BIN으로 저장한다.
  - `CAM_LEFT`, `CAM_RIGHT` image를 JPG로 저장한다.
  - calibration YAML을 우리 툴의 `calibration/calibration.json` 형식으로 변환한다.
  - ROS/OpenCV optical camera frame을 현재 projection 코드가 쓰는 tool camera frame으로 변환하는 옵션을 제공한다.
  - `log`, `publish`, `header`, `header_aligned` timestamp source를 지원한다.
  - 현재 one_chip 데이터는 `header_aligned`를 기본값으로 사용한다.
  - `sync/frames.jsonl` 생성 시 camera sample 반복·점프 QA를 report에 기록한다.
  - 기존 dataset의 BIN/JPG를 다시 쓰지 않고 `frames.jsonl`만 재생성하는 `--sync-only-existing`을 제공한다.
  - 기존 `frames.jsonl`을 교체하기 전에 `.bak-<timestamp>-<id>` 백업을 만든다.

- `scripts/verify_one_chip_calibration.py`
  - 변환된 `calibration.json`과 원본 calibration YAML 재생성 결과를 비교한다.
  - `MERGED` LiDAR transform이 identity인지 확인한다.
  - camera intrinsic, `T_camera_reference`, image size, distortion model을 검증한다.
  - 선택 frame/camera에 LiDAR point projection overlay 이미지를 만들 수 있다.

- `docs/20_ONE_CHIP_CONVERSION_MANUAL.md`
  - `E:\one_chip` 원본에서 `E:\one_chip_converted`를 만드는 절차를 정리했다.
  - `header_aligned` sync가 필요한 이유와 `log` timestamp 문제를 기록했다.
  - preflight, GUI 실행, 재변환, sync-only 재생성, calibration 검증 절차를 정리했다.

- `packaging/one_chip_run_pack/`
  - one_chip 작업용 실행 `.bat` 묶음이다.
  - preflight, GUI 실행, 전체 변환, sync-only 재생성, stats, calibration-only, portable build, calibration verify를 바로 실행할 수 있다.

- `tests/unit/test_one_chip_converter.py`
  - calibration 변환, verifier 비교, nearest sync tolerance, `header_aligned`, camera sample 반복·점프 QA를 검증한다.

### 새 박스 z 자동 보정

- `src/lidar_label_tool/geometry/box_fit.py`
  - 박스 XY footprint 안쪽 LiDAR point의 낮은 z percentile을 기준으로 floor z를 추정한다.
  - 원본 point cloud 배열은 수정하지 않는다.

- `src/lidar_label_tool/ui/main_window.py`
  - 새 박스 생성 시 `z = height / 2` 고정 대신 point floor를 추정해 `z = floor + height / 2`로 초기화한다.
  - 이미 생성된 박스는 `포인트 바닥에 맞춤` 버튼으로 z를 다시 맞출 수 있다.

- `src/lidar_label_tool/ui/panels/object_editor_panel.py`
  - `3D 박스 편집` 패널에 `포인트 바닥에 맞춤` 버튼을 추가했다.

- `tests/unit/test_box_fit.py`
  - point footprint floor 추정, box center z 보정, 포인트 부족 시 fallback, 원본 point 불변성을 검증한다.

### 실사용 피드백 매뉴얼

- `docs/19_TRIAL_RUN_MANUAL.md`
  - 사용자가 실제 데이터셋을 열고 문제를 재현·보고할 수 있는 절차와 피드백 양식을 추가했다.

- `README.md`, `docs/USER_MANUAL.md`
  - 실사용 테스트 매뉴얼 링크를 추가했다.
  - 새 박스 z 자동 보정과 `포인트 바닥에 맞춤` 사용법을 반영했다.

## c26cb7b — feat: optimize point cloud rendering and editing UX

렌더링 성능과 편집 UX를 개선한 커밋이다.

- 포인트 클라우드 렌더링 캐시 추가
  - `src/lidar_label_tool/ui/render_cache.py`
  - downsampled xyz/rgba를 표시용으로 캐시한다.
  - 원본 point cloud는 수정하지 않는다.

- 3D/BEV/SideView 렌더링 재사용
  - 같은 cloud/options이면 expensive numpy downsample/color 계산을 다시 하지 않는다.
  - 선택 객체나 박스만 바뀔 때 point cloud reload를 줄였다.

- MainWindow 렌더 invalidation 정리
  - 선택 변경, box line width 변경, point color/size 변경, side plane 변경의 rerender 범위를 분리했다.
  - Object Detail 3D 시점이 일반 편집/프레임 이동에서 초기화되지 않도록 조정했다.

- 키보드 편집 UX 개선
  - 이동/미세 이동/크기/회전 step 조절 UI를 추가했다.
  - 키보드 이동 시 전체 3D와 보조 뷰의 불필요한 시점 초기화를 줄였다.

- 상태 표시 개선
  - frame id, loaded/rendered point 수, object 수, dirty 상태, warning 수, active sensor를 간결하게 표시한다.

- 테스트/문서
  - `tests/unit/test_render_cache.py` 추가
  - `docs/18_PREFLIGHT_AND_QA.md`, `docs/15_IMPLEMENTATION_STATUS.md` 업데이트

## 1f30bf0 — feat: add phase 4 preflight stats and export validation

데이터셋 사전검수, 통계, export 신뢰성을 강화한 커밋이다.

- dataset preflight 서비스 추가
  - dataset 구조, frame 수, LiDAR/camera, point cloud file, image file, source label, calibration, working label, recovery snapshot을 검수한다.
  - structured report를 반환한다.

- CLI preflight 추가
  - `lidar-label-tool preflight <dataset>`
  - `--json` 출력 지원
  - error/warning 여부에 따라 exit code를 다르게 반환한다.

- GUI preflight 요약
  - dataset open 전 frame/LiDAR/camera/warning/error 요약을 표시한다.

- export validation 강화
  - NaN/Inf, 음수/0 크기, unknown class, invalid frame/dataset ID를 export 전에 차단한다.
  - multi-frame export가 부분적으로 깨진 파일을 남기지 않도록 batch validation을 강화했다.

- label statistics 추가
  - `lidar-label-tool stats <dataset>`
  - source/working label count, class별 object 수, frame 상태별 수, recovery count를 집계한다.

- 테스트/문서
  - dataset preflight, CLI, GUI preflight, label statistics, exporter validation 테스트 추가
  - `docs/18_PREFLIGHT_AND_QA.md` 추가

## 5afd73d — feat: add phase 3 recovery export and portable build

작업 안전성, export 체계, Windows portable 준비를 추가한 커밋이다.

- recovery snapshot 시스템
  - 저장 전 미저장 변경을 `.recovery/<frame_id>.recovery.json`에 별도 저장한다.
  - 정상 저장 시 recovery snapshot을 제거한다.
  - 앱 재시작 시 저장 label보다 새로운 recovery가 있으면 사용자에게 복구/무시/삭제를 묻는다.

- session lock
  - 같은 dataset/workspace를 두 GUI가 동시에 열 때 경고한다.
  - stale lock은 PID 확인 후 교체 가능하게 했다.

- exporter system 강화
  - 내부 JSON exporter
  - CenterPoint/OpenPCDet-style intermediate JSON exporter
  - CLI export command 추가
  - normal save와 export를 분리했다.

- camera image cache
  - overlay 변경 시 같은 image path를 불필요하게 다시 읽지 않도록 개선했다.

- Windows portable build 준비
  - `packaging/build_windows_portable.ps1`
  - `packaging/windows_entry.py`
  - `docs/17_WINDOWS_PORTABLE_BUILD.md`

- 테스트
  - recovery, session lock, exporter, CLI 테스트 추가

## 1709dfd — version2

1차 편집 GUI를 실제 작업 흐름에 가깝게 안정화한 커밋이다.

- BEV 편집 강화
  - 박스 이동, 모서리 resize, yaw rotate handle 추가
  - drag preview와 undo 단위 편집 지원

- SideView 편집 추가
  - z 이동과 height resize handle 지원

- UI panel 분리
  - camera panel, object editor panel을 일부 분리했다.

- sensor-level frame load 안정화
  - 일부 LiDAR return이 실패해도 다른 sensor/camera/label을 계속 열 수 있게 했다.

- exporter skeleton 추가
  - exporter protocol, registry, internal JSON exporter 기반 추가

- 테스트
  - BEV/SideView box edit geometry
  - frame loader partial failure
  - camera image view
  - device-centric adapter
  - exporter tests

## 1e2e288 — version 1

프로젝트 초기 기반과 1차 GUI/데이터 계약을 만든 커밋이다.

- 문서 기반 설계 추가
  - product spec, architecture, data contracts, open decisions, implementation plan, UX safety spec
  - calibration plan, distribution plan, sample audit, user manual

- 기본 domain/model/schema
  - `Box3D`, `LabeledObject`, `FrameLabel`
  - config/dataset/label/calibration JSON schema
  - coordinate convention: x forward, y left, z up, yaw around z

- adapter/loader 기반
  - frame-centric Waymo adapter
  - device-centric adapter
  - BIN/PCD loader
  - label repository와 Waymo source label importer

- GUI 기반
  - 전체 3D, camera, Object Detail 3D, BEV, side view
  - 기존 label import/display/edit/save
  - 새 박스 생성, 삭제, Undo/Redo, frame 이동

- calibration projection
  - Waymo camera calibration 기반 3D box projection
  - camera/source projected/live projection layer 표시

- 샘플 변환/검증 스크립트
  - Waymo sample을 merged device-centric dataset으로 변환하는 스크립트
  - GUI/interaction smoke script
