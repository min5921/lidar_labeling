# 확정된 결정사항

2026-07-05 사용자가 권장안 전체 적용을 승인했다. 아래 항목은 구현 기본값으로 확정한다.

| 번호 | 결정 내용 | 확정값 |
|---|---|---|
| D01 | 박스 z의 의미 | 내부·JSON은 기하 중심, 다른 포맷 export 시 변환 |
| D02 | 이미지가 없는 LiDAR 프레임 | 유지하고 경고/placeholder 표시 |
| D03 | BEV 박스 생성 | click-drag, 짧은 클릭은 기본 크기 |
| D04 | 측면 뷰 | x-z와 y-z 전환 |
| D05 | undo/redo | 포함(Ctrl+Z/Ctrl+Y) |
| D06 | 저장 보호 | atomic 저장 + 직전 `.bak` 1개 |
| D07 | 객체 ID | source 문자열 ID 보존, 신규 객체는 UUID 문자열 |
| D08 | 빈 프레임 | 빈 `objects` JSON 저장 |
| D09 | attributes | `difficulty` 문자열, `occluded`·`truncated` boolean |
| D10 | yaw 표시 | UI degree, 내부·JSON radian |
| D11 | 첫 배포 | portable ZIP 우선, 안정화 후 설치형 EXE |
| D12 | 운영체제 | Windows 10/11 x64 |
| D13 | 대상 PC Python | 설치 불필요 |
| D14 | 자동 업데이트 | 1차 제외, 수동 새 버전 설치 |
| D15 | calibration 시작 상태 | `auto`: source frame을 보고 sensor별 필요 여부 판정 |
| D16 | calibration OFF | transform 미적용; reference-frame 데이터만 병합, sensor-local은 raw 단독 보기 |
| D17 | calibration 기능 | 기존 값 적용, 수동 6DoF 미세조정, 전/후 비교, 저장 포함 |
| D18 | 자동 calibration 추정 | 1차 제외, 샘플 분석 후 별도 단계로 검토 |
| D19 | 정식 데이터 배치 | sensor/device 중심 구조 |
| D20 | 현재 frame 중심 샘플 | 원본 유지, 별도 adapter로 지원 |
| D21 | 기존 source label | 먼저 import/plot하고 편집 가능하게 함 |
| D22 | 편집 저장 | 원본 비덮어쓰기, 작업 라벨 atomic 저장 |
| D23 | 원 포맷 저장 | 별도 폴더로 명시적 export |
| D24 | 여러 카메라 | 모두 로드하되 1차 UI는 active camera 한 대씩 전환 |
| D25 | 운영 LiDAR 입력 | 여러 원본 LiDAR는 사전 보정·병합하고 앱에는 frame당 `MERGED` BIN/PCD 한 개만 입력 |

D25는 운영 GUI의 LiDAR 입력에 대해 D15~D17을 대체한다. LiDAR별 calibration 적용과 ON/OFF 비교는 원본→MERGED 전처리/검증 단계의 책임이며, 라벨링 GUI는 reference frame으로 확정된 MERGED 파일만 사용한다. Camera projection calibration은 GUI에서 계속 사용한다.

## 릴리스 직전에 정할 항목

- [ ] 앱 표시 이름: 임시안 `LiDAR Label Tool`
- [ ] EXE 파일 이름: 임시안 `LidarLabelTool.exe`
- [ ] 앱 아이콘 `.ico`
- [ ] 제작자/회사명과 저작권 문구
- [ ] 코드 서명 인증서 사용 여부
- [ ] 설치형 패키지 바로가기 정책

버전은 `MAJOR.MINOR.PATCH`, third-party license 포함, clean-PC 검증을 기본 정책으로 사용한다.

## 사용자가 전달할 실제 샘플

원본 구조 그대로 다음 위치에 넣는다.

```text
C:\Users\USER\Desktop\Labelling_tool\local_data\incoming\<dataset_name>\
```

가능하면 여러 LiDAR의 동일 frame 데이터, 대응 이미지, calibration 파일, 기존 라벨을 함께 둔다. calibration 파일이 없다면 센서 장착 위치/방향 또는 변환 과정에 대한 설명도 도움이 된다.

## 샘플로 검증할 기술 항목

- sensor 목록, primary LiDAR, frame ID 매칭 규칙
- sensor별 `.bin` 구조와 intensity 범위
- 각 sensor 좌표축과 reference frame 정의
- calibration 행렬 방향·단위·static/frame별 여부
- camera intrinsic, distortion, `T_camera_reference`
- LiDAR별 timestamp 차이와 motion compensation 필요성
- 대표 프레임 포인트 수와 렌더링 한도
- 한글·공백 경로와 clean Windows 배포본 실행
