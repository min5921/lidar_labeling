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
| D11 | 내부 운영 | Windows/Linux 소스 + 고정 가상환경 |
| D12 | 운영체제 | Windows 10/11 x64 |
| D13 | 대상 PC Python | 현재 source 운영본은 공식 64-bit Python 3.10+ 설치 필요; 새 Windows PC는 python.org Python 3.12 권장 |
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

## 범용 데이터셋 v2 추가 결정

2026-08-07 범용 데이터 폴더 구성과 profile 기반 편집 계약을 확정했다. 아래 결정은 v2
데이터셋에 대해 D15~D17, D24, D25의 운영 입력 범위를 대체한다. 기존 v1/Waymo/one_chip
데이터는 호환 경로에서 기존 의미를 유지한다.

| 번호 | 결정 내용 | 확정값 |
|---|---|---|
| D26 | v2 LiDAR inventory | label-ready LiDAR 후보 1개 이상 등록 가능 |
| D27 | 편집 단위 | profile당 활성 LiDAR 정확히 1개, 편집 세션도 profile 하나 |
| D28 | LiDAR 병합 | 앱 내부 자동 병합과 동시 box fitting 금지 |
| D29 | v2 카메라 | profile당 0개 또는 1개, `display_only`/`calibrated` 구분 |
| D30 | Dataset 구성 | `dataset.json`이 없으면 오류 대신 구성 마법사로 생성 |
| D31 | 동기화 | LiDAR anchor, 명시적 method/tolerance, QA 확인 후 frozen frame index 생성 |
| D32 | Frame identity | `frame_id`는 활성 LiDAR의 안전한 논리 `sample_id`와 같고 재동기화로 변경 금지; 원본 ID/path 별도 보존 |
| D33 | Label identity | `dataset_id + profile_id + label_lidar_id + frame_id`, profile/LiDAR별 저장 namespace |
| D34 | ID와 표시 이름 | machine ID는 안전한 소문자 ASCII, 한글·공백은 `display_name`에 보존 |
| D35 | 읽기 전용 원본 | 외부 configuration workspace와 명시적 `data_root` overlay 지원 |
| D36 | v1 호환 | v1은 계속 읽고 새 마법사는 v2만 생성, migration은 명시적·비파괴적으로 수행 |
| D37 | Dataset taxonomy | v2는 stable `class_id`와 별도 `taxonomy.json`을 사용 |
| D38 | Recovery와 lock identity | recovery는 frame scope, session lock은 profile/LiDAR namespace scope로 분리 |
| D39 | 현재 배포 방식 | `codex/v2` source + lock 기반 `.venv`; Python 미설치 portable은 현재 운영 경로 아님 |
| D40 | 프레임 간 수동 객체 연결 | 같은 profile에서 기준 객체를 기억하고 현재 frame에 복사 또는 기존 객체의 ID 연결; 단일 frame undo/원자 저장 |
| D41 | 분할 폴더 간 객체 이어받기 | 같은 LiDAR·좌표계의 연속 데이터에서 이전 작업 JSON의 선택 객체를 현재 frame에 일괄 복사; 기존 ID는 건너뛰고 대상 frame identity 유지 |
| D42 | 선택 객체 1-step 추적 보조 | 사용자가 켠 경우 순차 다음 frame의 포인트로 선택 객체 x/y 및 선택적 z만 조정; 크기·yaw 유지, 불확실하면 원위치 |
| D43 | 자동 z 보정 방식 | 기본은 객체 포인트 이동량; 지면 보정은 기본 OFF이고 실행 중 객체 ID별 opt-in, 다른 객체 선택에 전파 금지 |
| D44 | 선택 포인트 표시 | 선택 3D 박스 내부의 표시 포인트를 노란색으로 강조; 원본 point/색상/라벨은 변경하지 않음 |
| D45 | 객체별 순차 작업과 재추적 | 자동 추적 ON에서는 선택 객체만 이어받음; 기존 박스 재추적은 기본 OFF·실행 중 ID별 opt-in이며 완료/건너뜀/복구 라벨 보호 |

D40은 사용자가 명시적으로 연결한 작업 객체에 대해 D07의 ID 보존 예외다. 원본 source 파일과
source metadata는 보존하고 이전 작업 ID를 연결 이력에 남긴다. 다른 frame들의 ID를 일괄
변경하거나 자동으로 추적·보간하지 않는다.

D41은 D40의 같은 profile 내 연결과 별도의 명시적 객체 복사다. dataset/profile ID가 달라도
LiDAR ID, reference frame, 단위·축·yaw 계약이 같아야 하며 좌표 변환은 하지 않는다. 이전
프레임의 ID·class·box·metadata를 보존하고, 현재 폴더의 frame/path/revision/provenance로 저장한다.
전체 가져오기는 한 번의 Undo로 취소하며 이후 순차 다음 프레임 이어받기 대상에 포함한다.
자동 추적 OFF에서는 만든/가져온 객체를 모두 이어가고, ON에서는 선택한 객체 하나만 이어간다.
폴더 자동 전환, 폴더 경계 자동 추적·보간, 전체 라벨 파일의 identity 변경은 지원하지 않는다.

D42는 자동 tracking 보류 범위 중 **선택 객체의 바로 다음 프레임 이동 보조**만 추가한다.
학습 모델, 전체 객체 자동 추적, 회전/크기 추정, 과거·건너뛴 프레임의 보간은 여전히 보류한다.
단일 LiDAR의 같은 reference frame만 사용하고 기존 대상 ID·원본 source 파일·복구 라벨을
보존한다. 기본은 기존 박스 위치도 유지하며 D45의 명시적 재추적만 예외다.
이동은 대상 frame의 별도 Undo 동작이고 결과는 사용자가 확인해야 한다.
D45는 객체 하나씩 전체 구간을 작업할 때 다른 객체의 미편집 사본이 미리 저장되지 않게 한다.
선택이 없으면 자동 추적 모드에서는 아무 객체도 복사하지 않는다. `선택 객체: 기존 박스도
다시 추적`은 현재 실행의 해당 ID에만 적용하고 다음 frame의 같은 클래스·미완료 박스 위치만
갱신한다. 대상의 크기·yaw·속성·unknown field와 다른 객체는 유지한다. 검토 완료/건너뜀,
복구 복원, snapshot 불일치, 불확실한 결과는 적용하지 않는다. 이미 자동 복사된 박스와
수동으로 수정한 미완료 박스를 자동 판별하지 않으며, 기존 파일 삭제/일괄 정리는 하지 않는다.
D43의 지면 옵션은 차량·사람처럼 지면에 붙은 객체에만 켠다. 공중 표지판에는 기본 포인트
이동량 방식을 사용하며, 충분한 지면 근거가 없으면 이전 z를 유지한다. 지면 평면은 안전성 확인에
사용하고, 최종 높이는 `B`와 동일한 footprint 하위 5% 포인트 높이로 맞춘다. 따라서 동일한
포인트·footprint에서 자동 보정 뒤 `B`를 눌러도 높이가 다시 변하지 않는다. `B`는 현재 frame에
명시적으로 적용하는 수동 동작이며 자동 지면 보정의 opt-in/신뢰도/이동 한도와는 별개다.

상세 규범은 `docs/32_GENERIC_DATASET_V2_CONTRACT.md`와 다음 schema를 따른다.

- `schemas/dataset-v2.schema.json`
- `schemas/frame-index-v2.schema.json`
- `schemas/label-v2.schema.json`
- `schemas/taxonomy.schema.json`
- `schemas/recovery-v2.schema.json`
- `schemas/session-lock-v2.schema.json`

## 릴리스 직전에 정할 항목

- [ ] 앱 표시 이름: 임시안 `LiDAR Label Tool`
- [x] Python 미설치 실행 파일 배포는 내부 운영 범위에서 제외
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
- 한글·공백 경로와 clean Windows/Linux 가상환경 실행
