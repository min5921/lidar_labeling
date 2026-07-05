# 프로젝트 재검수 결과

검수 기준은 요구사항 누락, 계층 의존성, 데이터 손상 위험, 좌표계 모호성, UI 상태 일관성, 성능, 다른 PC 배포 가능성이다.

## 양호한 부분

- domain, I/O, service, UI, geometry가 분리되어 확장에 유리하다.
- 좌표축, 단위, yaw, box dimension 순서를 문서로 고정했다.
- 프레임 목록 기준과 누락 이미지 처리 기본안이 있다.
- 단일 session이 선택과 편집 상태를 소유하여 뷰 간 불일치를 막는다.
- JSON Schema와 atomic save 정책으로 저장 안정성을 준비했다.
- loader/exporter 확장 지점이 UI에서 분리되어 있다.
- 구현 단계를 domain/I/O/읽기 GUI/편집/저장/투영/배포 순으로 나눴다.

## 보완하여 반영한 부분

- 사용자 선택과 기술 검증 항목을 분리했다.
- Windows 배포를 1차 릴리스 범위와 완료 기준에 추가했다.
- frozen 앱에서 resource와 사용자 쓰기 경로를 분리했다.
- clean Windows, Python 미설치, 한글/공백 경로 검증을 추가했다.
- portable ZIP → 설치형 EXE 순서로 릴리스 위험을 낮췄다.
- 권장안 전체 승인 결과를 구현 기본값으로 확정했다.
- 멀티 LiDAR calibration 적용·ON/OFF·수동 6DoF 조정 설계를 추가했다.
- 전달된 198-frame Waymo-style 샘플을 검사하고 Nx6/device 목록/source label 계약을 반영했다.
- 정식 device 중심 입력과 현재 frame 중심 입력을 adapter로 분리했다.

## 구현 중 특히 주의할 위험

### 1. OpenGL renderer와 배포

개발 PC에서만 보이는 Qt/OpenGL plugin 의존성이 생길 수 있다. Phase 0에서 작은 배포 spike를 먼저 만들고 clean PC에서 실행해야 한다.

### 2. 카메라 투영 좌표계

행렬 방향 또는 camera 축을 잘못 해석하면 그럴듯하지만 틀린 결과가 나온다. 합성 calibration 수치 테스트와 실제 이미지 시각 검증을 둘 다 요구한다.

### 3. 대용량 포인트 클라우드

원본과 표시용 배열을 분리하고 불필요한 복사를 피해야 한다. 대표 데이터 없이 `max_render_points`를 확정하지 않는다.

### 4. 편집 상태 손실

프레임 이동, 앱 종료, 저장 실패 순서가 꼬이면 라벨이 사라질 수 있다. dirty 상태와 저장 명령을 service 하나에서 관리하고 실패 시 이동을 중단한다.

### 5. 배포본 쓰기 경로

EXE 또는 bundle 내부에 설정/로그를 쓰면 설치 위치 권한에 따라 실패한다. bundle resource는 읽기 전용, 사용자 파일은 OS application-data 경로로 분리한다.

### 6. 3D box picking

pyqtgraph.opengl이 요구 수준의 object picking을 바로 제공하지 않을 수 있다. 3D 좌클릭 선택은 요구사항으로 유지하되 Phase 3 초기에 screen-space edge picking을 포함한 작은 prototype으로 확정한다. BEV와 객체 목록 선택은 항상 사용할 수 있어야 한다.

## 구현 착수 판정

아키텍처와 단계 계획은 구현 가능한 수준이며 권장안 승인과 실제 샘플 검사도 완료되었다. 구현 착수 전에 남은 조건은 Python 개발환경 구성과 PySide6/OpenGL 배포 spike 성공이다.

상세 위험도와 사용자 보호 동작은 `docs/13_PRE_IMPLEMENTATION_AUDIT.md`, `docs/14_UX_SAFETY_SPEC.md`를 구현 계약으로 사용한다.
