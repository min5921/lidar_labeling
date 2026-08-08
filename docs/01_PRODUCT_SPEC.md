# 제품 요구사항

> 현재 기본 제품 범위는 범용 데이터셋 v2다. 기존 `MERGED + 다중 camera`, Waymo와 one_chip은
> 호환·레거시 입력으로 유지한다. 세부 identity와 저장 계약은
> `docs/32_GENERIC_DATASET_V2_CONTRACT.md`를 우선한다.

## 목표

이미 파일로 정리된 LiDAR 후보와 선택적 camera를 프로그램에서 범용 v2 데이터셋으로 구성한다.
한 profile의 label-ready LiDAR 한 개를 기준으로 3D bounding box를 생성·선택·이동·크기
조절·회전·삭제하고, profile/LiDAR identity가 분리된 frame별 JSON으로 안전하게 저장하는
데스크톱 GUI를 제공한다.

## 1차 릴리스 범위

- Windows/Linux source 실행과 Python 3.10+ 고정 가상환경
- PySide6 기반 데스크톱 GUI
- manifest/schema가 column을 선언하는 float32 `N x C` `.bin` 또는 PCD 포인트 클라우드
- JSON이 없는 폴더의 LiDAR/camera/timestamp 후보 탐색과 v2 구성 마법사
- 여러 LiDAR 후보를 센서별 독립 profile로 등록하고 세션당 하나만 활성화
- profile당 camera 0개 또는 1개
- LiDAR-only, exact-stem, timestamp-nearest 동기화와 고정 frame index generation
- 읽기 전용 원본용 외부 configuration/annotation workspace
- 기존 v1 device 중심, Waymo frame 중심, one_chip 입력 adapter 호환
- `.jpg`, `.jpeg`, `.png` 카메라 이미지
- 3D, BEV, 측면, 카메라 이미지 뷰
- 기존 JSON 라벨 로드 및 신규/수정 라벨 저장
- 기존 Waymo-style 3D/2D/projected label layer 표시
- source label import, 작업 라벨 우선 재로드, 별도 export
- 클래스 선택, 객체 목록, 수치 편집 패널
- 이전/다음 프레임 이동과 이동 전 자동 저장
- 키보드 및 기본 마우스 편집
- 보정값이 있을 때만 이미지 위 3D 박스 투영
- camera calibration 자동 감지와 projection ON/OFF
- 앱 내부 LiDAR 자동 병합 금지와 profile/LiDAR별 label namespace
- 사용자 설정 파일 기반 클래스와 기본 박스 크기
- source/working label 분리, 원자적 저장, fingerprint/revision 충돌 검출

## 1차 릴리스에서 제외

- 자동 라벨링 및 AI 추론
- 특징점/ICP/target 기반 calibration 값 자동 추정
- 여러 카메라를 한 화면에 동시에 펼치는 mosaic 표시
- 포인트 단위 세그멘테이션
- 협업 서버, 사용자 계정, 원격 저장
- KITTI/OpenPCDet 내보내기의 완성 구현
- `.npy`, point-cloud `.csv`, compressed PCD 실제 지원
- 프레임 간 트래킹 및 박스 보간
- 자동 업데이트와 Python 미설치용 단일 실행 파일 배포

## 화면 구성

- 중앙/좌측: 3D 포인트 클라우드
- 우측 상단: 카메라 이미지
- 좌측 하단: BEV(x-y)
- 우측 하단: x-z/y-z 전환 가능한 측면 뷰
- 우측 패널: 프레임 정보, 클래스, 객체 목록, 박스 수치, 편집/저장/이동 버튼

레이아웃은 splitter 기반으로 크기를 조절할 수 있어야 한다.

## 핵심 사용자 흐름

1. 원본 폴더 또는 기존 데이터셋을 연다.
2. `dataset.json`이 없으면 후보 탐색 결과에서 LiDAR, point columns, 좌표계, 선택적 camera와
   timestamp 설정을 확인한다.
3. 구성 분석의 frame/match/unmatched/reuse QA를 확인한 뒤 검증 결과로 v2 generation을 만든다.
4. 데이터셋을 열 때 이번 세션에서 사용할 LiDAR profile 하나를 선택한다.
5. 작업 라벨이 있으면 그것을, 없으면 기존 source label 또는 빈 label을 먼저 표시한다.
6. BEV에서 기존 객체를 수정하거나 새 객체를 만들고 이동/회전/크기를 조절한다.
7. 측면 뷰 또는 수치 패널에서 z와 높이를 조절한다.
8. 모든 뷰에서 동일한 선택 객체와 변경 결과를 확인한다.
9. 작업 JSON을 원자적으로 저장하고 필요할 때 별도 형식으로 명시적으로 export한다.

## 성공 기준

- 샘플 `.bin + .jpg/.png` 프레임을 오류 없이 표시한다.
- 박스 편집 결과가 네 뷰와 수치 패널에 즉시 동기화된다.
- 앱 재시작 후 저장된 객체의 값과 ID가 동일하게 복원된다.
- 보정 폴더가 없어도 이미지 표시와 LiDAR 라벨링이 정상 동작한다.
- 한 세션에서는 정확히 한 LiDAR만 로드하며 다른 profile의 같은 frame ID 라벨과 충돌하지 않는다.
- camera 또는 calibration이 없어도 모든 정상 LiDAR frame을 라벨링하고 저장할 수 있다.
- sync 실패나 이미지 누락이 LiDAR frame 수와 순서를 줄이지 않는다.
- BIN point columns, coordinate frame, timestamp column/unit/clock domain을 조용히 추측하지 않는다.
- 현재 샘플의 기존 `laser_labels`, `camera_labels`, `projected_lidar_labels`를 layer별로 표시할 수 있다.
- 기존 v1/Waymo 샘플에서는 여러 카메라를 전환하고 camera별 source label과 live projection을
  표시할 수 있다.
- 기존 3D box를 수정·삭제하고 새 box를 추가한 결과가 원본을 훼손하지 않고 재로드된다.
- 손상 파일은 앱 전체 종료 대신 해당 프레임 오류로 보고된다.
- 깨끗한 Windows/Linux Python 3.10+ 가상환경에서 데이터 열기·편집·저장 smoke test가 통과한다.
- 빠른 frame 이동 중 오래된 background load 결과가 현재 frame을 덮지 않는다.
- 앱 비정상 종료 후 recovery 후보를 안내하고 마지막 명시 저장본은 손상되지 않는다.
- 출력 폴더가 쓰기 불가능하면 작업 시작 전에 별도 workspace를 선택하게 한다.
