# 구현 재검수 결과

> 이 문서는 과거 단계의 구현 검토 기록이다. 현재 상태는 `docs/15_IMPLEMENTATION_STATUS.md`,
> 현재 설치·운영 기준은 `docs/31_LAB_SOURCE_SETUP.md`를 따른다.

최초 검수일: 2026-07-06
후속 재검수: 2026-07-10

## 2026-07-10 후속 결과

아래 2026-07-06 본문은 당시 snapshot이다. 이후 device 중심 입력, `MERGED` 운영 구조,
recovery/session lock, 직접 조작 handle, preflight/stats/export, one_chip 변환·동기화·calibration
검증, PyInstaller portable 배포본이 구현됐다.

이번 후속 검수에서는 simple output manifest의 Schema 불일치, frozen config의 작업 폴더 fallback,
EXE 옆 crash log, 수작업 릴리스 조립, source/calibration 변경 미경고, unknown working label field
손실을 수정했다. 현재 남은 배포 Gate는 별도 Python 미설치 clean Windows PC에서의 최종
open/edit/save 인증, 코드 서명, third-party license 정리다.

## 2026-07-06 당시 snapshot

## 결론

프로젝트 방향과 핵심 데이터 안전 원칙은 목표에 맞게 유지되고 있다. 현재 상태는 전달받은 Waymo-style frame 중심 샘플을 개발 PC에서 열고, 기존 3D 라벨을 수정해 별도 작업 JSON으로 안전하게 저장할 수 있는 **사용자 시험용 프로토타입**이다.

아직 비개발자에게 배포할 수 있는 1차 완제품은 아니다. 정식 device 중심 입력, sensor-local 멀티 LiDAR calibration, 복구/session lock, 직접 조작 handle, portable 배포 검증이 남아 있다.

## 목표 대비 상태

| 영역 | 상태 | 검수 결과 |
|---|---|---|
| 현재 frame 중심 샘플 입력 | 완료 | 198 frame, LiDAR 5대, camera 5대 인식 |
| 기존 3D 라벨 우선 표시 | 완료 | source ID/class/box를 import하고 작업 라벨이 있으면 우선 로드 |
| 원본 비덮어쓰기 | 완료 | `labels/`는 읽기 전용, 결과는 `annotations/lidar_label_tool/`에 저장 |
| 안전 저장 | 완료 | 임시 파일 검증, atomic replace, revision 충돌 감지, `.bak` 생성 |
| 객체 선택 일관성 | 부분 완료 | 객체 목록·전체 3D·BEV 선택이 3D/BEV/side/camera에 반영됨. side/camera 직접 picking은 미구현 |
| 박스 편집 | 완료 | 수치·키보드 편집, BEV 생성·이동·크기·yaw handle, SideView z·height handle, 삭제, undo/redo 지원 |
| 포인트 표시 | 완료 | sensor/height/intensity/uniform 색상과 크기 조절 |
| 카메라 투영 | 현재 샘플 완료 | camera calibration, near/image clipping, camera-synced box 기반 live 3D wireframe |
| 멀티 LiDAR calibration | 부분 완료 | device adapter가 sensor-local transform을 Auto 적용. ON/OFF·수동 6DoF UI는 후속 |
| device 중심 정식 입력 | 완료 | 번호형 device 폴더, exact-stem 및 `frames.jsonl` index 지원 |
| 부분 센서 오류 격리 | 완료 | sensor/return별 오류를 수집하고 정상 cloud 또는 camera/label이 있으면 frame을 계속 표시 |
| 비정상 종료 복구/session lock | 미완료 | 명시 저장과 frame 이동 autosave는 있으나 recovery snapshot과 lock은 없음 |
| 사용자 배포 | 미완료 | 개발 실행만 가능. Python 미설치 PC용 portable ZIP은 아직 없음 |

## 사용자 편의 검수

### 현재 좋은 점

- 선택 객체가 모든 뷰에서 노란색 굵은 선으로 표시된다.
- 독립 Camera GT, 원본 projected label, 현재 작업 박스 투영을 명확히 구분한다.
- 표시용 포인트 설정이 원본 데이터와 라벨을 변경하지 않는다.
- 잘못 만든 박스와 삭제를 Undo로 복구할 수 있다.
- frame 이동 전에 자동 저장하며 저장 실패 시 이동하지 않는다.
- source label과 working label의 책임이 분리되어 있다.

### 이번 재검수에서 바로 개선한 내용

- dataset 경로를 생략하면 폴더 선택 창이 열리도록 변경했다.
- `run_gui.bat`을 추가해 현재 개발 PC에서 명령어 없이 실행할 수 있게 했다.
- 주요 패널 용어를 한국어로 정리했다.
- 현재 frame/전체 frame, 라벨 출처, revision, 미저장 상태를 표시한다.
- 실제 작업 JSON 저장 위치를 화면에 표시한다.
- 미저장 상태일 때 창 제목에 `*`를 표시한다.
- camera live projection의 보정 적용 여부를 text로 표시한다.
- 기존 객체 클래스와 새 박스 클래스 입력을 분리해 우발적인 클래스 변경을 막았다.
- 우측 패널에 최소 조작 순서를 항상 표시한다.
- dataset open 전에 frame/sensor/좌표계/라벨/calibration/작업 경로 요약을 표시한다.
- 실제 작업 폴더에 probe file을 생성·삭제해 저장 가능 여부를 확인한다.
- dataset이 읽기 전용이면 별도 annotation workspace를 선택할 수 있다.

### 사용자 시험 전에 우선 해결할 항목

1. recovery snapshot과 session lock
2. frame `reviewed/skipped` 처리와 다음 미검토 frame 이동
3. projection의 시간 동기화·motion compensation 한계를 나타내는 정확도 상태
4. Python 미설치 Windows PC용 portable 배포와 clean-PC 검증

## 안전성 판단

- 원본 데이터 보호: 적합
- 작업 JSON 저장 실패 시 기존 파일 보호: 적합
- 외부 작업 JSON 변경 충돌 감지: 적합
- 빠른 frame 이동의 오래된 load 차단: 적합
- source fingerprint 재검사, recovery, session lock: 보완 필요
- sensor-local LiDAR를 calibration 없이 조용히 병합하지 않는 기능: 적합. Missing/Invalid/Disabled 센서는 제외하고 상태를 표시

## 다음 구현 순서 권장안

1. recovery/session lock 및 저장 상태 강화
2. LiDAR calibration ON/OFF·수동 조정과 sensor별 상태 표시
3. exporter GUI 연결과 source-compatible 형식 구현
4. portable 배포 spike와 clean Windows 검증
