# 제품 요구사항

## 목표

frame별로 공통 reference 좌표에 사전 병합된 LiDAR 포인트 클라우드 한 개와 여러 카메라 이미지를 함께 연다. 그 위에서 3D 바운딩 박스를 생성·선택·이동·크기 조절·회전·삭제한 뒤 프레임별 JSON으로 안전하게 저장하는 데스크톱 GUI를 만든다.

## 1차 릴리스 범위

- Python 3.10+
- PySide6 기반 데스크톱 GUI
- manifest/schema가 column을 선언하는 float32 `N x C` `.bin` 또는 PCD 포인트 클라우드
- 장치 폴더 안에 모든 frame을 보관하는 `MERGED/<sample_id>.bin|pcd` 입력
- 여러 camera device 로드와 active camera 전환
- device 중심 정식 입력과 기존 frame 중심 샘플 입력 adapter
- `.jpg`, `.jpeg`, `.png` 카메라 이미지
- sync index 우선, 동일 stem 차선의 명시적 frame 매칭
- 3D, BEV, 측면, 카메라 이미지 뷰
- 기존 JSON 라벨 로드 및 신규/수정 라벨 저장
- 기존 Waymo-style 3D/2D/projected label layer 표시
- source label import, 작업 라벨 우선 재로드, 별도 export
- 클래스 선택, 객체 목록, 수치 편집 패널
- 이전/다음 프레임 이동과 이동 전 자동 저장
- 키보드 및 기본 마우스 편집
- 보정값이 있을 때만 이미지 위 3D 박스 투영
- camera calibration 자동 감지와 projection ON/OFF
- 원본 멀티 LiDAR 변환기는 각 LiDAR를 공통 reference frame으로 만든 뒤 단일 파일로 병합
- 사용자 설정 파일 기반 클래스와 기본 박스 크기
- Python이 설치되지 않은 다른 Windows PC에서 실행 가능한 배포본

## 1차 릴리스에서 제외

- 자동 라벨링 및 AI 추론
- 특징점/ICP/target 기반 calibration 값 자동 추정
- 여러 카메라를 한 화면에 동시에 펼치는 mosaic 표시
- 포인트 단위 세그멘테이션
- 협업 서버, 사용자 계정, 원격 저장
- KITTI/OpenPCDet 내보내기의 완성 구현
- `.pcd`, `.npy`, `.csv` 실제 지원(확장 지점만 준비)
- 프레임 간 트래킹 및 박스 보간
- 1차 릴리스의 자동 업데이트와 Windows 외 운영체제 배포

## 화면 구성

- 중앙/좌측: 3D 포인트 클라우드
- 우측 상단: 카메라 이미지
- 좌측 하단: BEV(x-y)
- 우측 하단: x-z/y-z 전환 가능한 측면 뷰
- 우측 패널: 프레임 정보, 클래스, 객체 목록, 박스 수치, 편집/저장/이동 버튼

레이아웃은 splitter 기반으로 크기를 조절할 수 있어야 한다.

## 핵심 사용자 흐름

1. 데이터셋 루트를 연다.
2. device 중심 폴더와 동기화 index를 읽어 논리 `FrameBundle`을 만든다. 기존 frame 중심 자료는 변환기 또는 별도 adapter가 같은 결과로 바꾼다.
3. `MERGED` LiDAR가 manifest의 reference frame으로 선언되었는지 확인한다.
4. 원본 센서별 calibration과 병합은 입력 데이터 생성 단계에서 수행하고 provenance를 남긴다.
5. 작업 라벨이 있으면 그것을, 없으면 기존 source label을 import하여 먼저 표시한다.
6. BEV에서 기존 객체를 수정하거나 새 객체를 만들고 이동/회전/크기를 조절한다.
7. 측면 뷰 또는 수치 패널에서 z와 높이를 조절한다.
8. 모든 뷰에서 동일한 선택 객체와 변경 결과를 확인한다.
9. 작업 JSON을 원자적으로 저장하고 필요할 때 source-compatible 형식으로 별도 export한다.

## 성공 기준

- 샘플 `.bin + .jpg/.png` 프레임을 오류 없이 표시한다.
- 박스 편집 결과가 네 뷰와 수치 패널에 즉시 동기화된다.
- 앱 재시작 후 저장된 객체의 값과 ID가 동일하게 복원된다.
- 보정 폴더가 없어도 이미지 표시와 LiDAR 라벨링이 정상 동작한다.
- MERGED 파일의 좌표계가 manifest reference frame과 다르면 라벨링을 시작하지 않고 전처리 재생성을 안내한다.
- 원본→MERGED 변환 결과는 동일 입력과 calibration에서 point 수와 좌표가 재현된다.
- 현재 샘플의 기존 `laser_labels`, `camera_labels`, `projected_lidar_labels`를 layer별로 표시할 수 있다.
- 현재 샘플의 5개 카메라를 전환하고 camera별 source label과 live projection을 표시할 수 있다.
- 기존 3D box를 수정·삭제하고 새 box를 추가한 결과가 원본을 훼손하지 않고 재로드된다.
- 손상 파일은 앱 전체 종료 대신 해당 프레임 오류로 보고된다.
- 깨끗한 Windows x64 환경에서 portable 배포본으로 데이터 열기·편집·저장 smoke test가 통과한다.
- 빠른 frame 이동 중 오래된 background load 결과가 현재 frame을 덮지 않는다.
- 앱 비정상 종료 후 recovery 후보를 안내하고 마지막 명시 저장본은 손상되지 않는다.
- 출력 폴더가 쓰기 불가능하면 작업 시작 전에 별도 workspace를 선택하게 한다.
