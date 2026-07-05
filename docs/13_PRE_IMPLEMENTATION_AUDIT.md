# 구현 전 충돌·위험 검수

검수 기준은 데이터 손상, 좌표/보정 오류, 비동기 상태 충돌, 기존 라벨 호환성, 렌더링 성능, 사용자 실수, 배포 환경이다. 위험도는 P0(구현 전에 설계 고정), P1(첫 사용자 테스트 전 해결), P2(후속 개선)로 구분한다.

## 검수에서 발견해 바로 정정한 충돌

| 항목 | 기존 충돌 | 정정 결과 |
|---|---|---|
| BIN 형식 | 일부 문서가 Nx4/16-byte로 고정, 실제 샘플은 Nx6/24-byte | manifest column 수 기반 NxC loader로 통일 |
| frame 매칭 | 단순 stem 자동 매칭과 sync index 정책 혼재 | index 우선, exact stem 차선, timestamp nearest는 명시적 선택 |
| 라벨 위치 | `labels/`와 작업 `annotations/`가 혼재 | source는 읽기 전용, 작업은 `annotations/lidar_label_tool/` |
| calibration OFF | primary만 표시와 reference-frame 데이터 병합 정책 혼재 | transform만 끄고 reference-frame 데이터는 병합 허용 |
| 측면 뷰 | x-z 고정 여부가 미결정으로 남음 | x-z/y-z 전환으로 확정 |
| undo/redo | 승인 완료 후에도 미결정 문구가 남음 | frame별 Ctrl+Z/Ctrl+Y로 확정 |
| 멀티 카메라 | active camera 지원과 후속 기능 표현이 겹침 | 1차는 한 대씩 전환, 동시 mosaic만 후속 |
| loader 인터페이스 | `load(path)`만으로 NxC column/좌표 frame 전달 불가 | `load(path, PointCloudSpec)`로 변경 |
| point 표현 | UI가 raw column index에 의존할 위험 | canonical `xyz + named attributes`로 분리 |
| exporter 책임 | source exporter와 generic exporter가 중복 | `LabelExporter` protocol 하나로 통합 |
| working label 소유권 | adapter와 repository의 경계가 불명확 | adapter는 source-only, service가 working label을 조합 |

## P0 — 구현 전에 반드시 막을 위험

### R01. Calibration 이중 적용

- 발생: 이미 vehicle/reference frame인 현재 BIN에 LiDAR extrinsic을 다시 적용
- 결과: 모든 센서가 체계적으로 어긋나지만 화면상 그럴듯해 발견이 늦음
- 예방: sensor마다 source coordinate frame 필수, 상태를 `Not required/Applied/Missing/Invalid/Disabled`로 계산
- 사용자 동작: 적용된 행렬과 이유를 sensor panel에서 확인하고 Auto 판정을 수동 override 가능

### R02. 변환 행렬 방향 오류

- 발생: Waymo `extrinsic.transform`을 `T_camera_vehicle`인지 반대인지 확인 없이 사용
- 결과: 이미지 projection이 틀리거나 화면 밖으로 사라짐
- 예방: adapter 경계에서 `T_target_source`로 변환, inverse/round-trip 수치 테스트와 실제 이미지 검증
- 사용자 동작: source/target frame 이름과 projection 상태를 항상 표시

### R03. 잘못된 sensor 동기화

- 발생: device별 sample ID가 다르지만 같은 순서 또는 가까운 timestamp만으로 자동 결합
- 결과: 움직이는 객체가 이중으로 보이고 라벨 품질 저하
- 예방: sync index 우선, exact stem 차선, nearest는 tolerance와 사용자의 명시적 활성화 필요
- 사용자 동작: frame별 sensor timestamp 차이와 누락 sensor badge 확인

### R04. 오래된 비동기 load가 최신 frame을 덮음

- 발생: 사용자가 D를 빠르게 누른 뒤 이전 frame worker가 늦게 완료
- 결과: 화면 frame 번호와 실제 point/label이 달라지는 심각한 오라벨
- 예방: 모든 load에 request generation/frame ID를 부여하고 최신 요청만 commit
- 사용자 동작: loading 중 frame ID를 표시하고 불일치 결과는 조용히 폐기

### R05. 원본 또는 다른 작업자의 변경 덮어쓰기

- 발생: 두 앱 인스턴스 또는 외부 프로그램이 같은 working JSON을 수정
- 결과: 최신 편집 손실
- 예방: dataset session lock, revision/source fingerprint 비교, atomic save
- 사용자 동작: 충돌 시 overwrite 대신 reload/save-as/cancel 선택

### R06. Calibration 변경 후 기존 라벨 오해

- 발생: 작업 라벨 생성 뒤 active calibration이 변경됨
- 결과: box 좌표는 같지만 point 정렬이 바뀌어 라벨이 틀린 것처럼 보이거나 실제로 재검토 필요
- 예방: working label에 calibration fingerprint 저장
- 사용자 동작: fingerprint가 다르면 `보정 변경 후 미검토` 경고와 frame 재검토 표시

### R07. 쓰기 불가능한 dataset

- 발생: 읽기 전용 디스크, 네트워크 폴더, 권한 제한 위치
- 결과: 편집 후 저장 단계에서 뒤늦게 실패
- 예방: dataset open 단계에서 probe file로 쓰기 가능 여부 확인
- 사용자 동작: 작업 시작 전 별도 annotation workspace 선택

### R08. source label 정보 손실

- 발생: Waymo 문자열 ID, `TYPE_SIGN`, velocity/difficulty 등 알 수 없는 field를 내부 모델이 버림
- 결과: export 후 원본과 의미가 달라짐
- 예방: source ID 문자열 보존, known field 정규화 + unknown metadata 보존, round-trip fixture
- 사용자 동작: export 전에 손실/변환 report 제공

### R09. Qt/OpenGL thread 충돌

- 발생: worker thread에서 GL item 또는 Qt widget 변경
- 결과: 간헐 crash와 재현 어려운 화면 손상
- 예방: worker는 NumPy/JSON 처리만, UI/GL 변경은 main thread signal로 수행
- 사용자 동작: crash 대신 frame별 오류와 재시도 제공

### R10. 외부 workspace의 frame ID 충돌

- 발생: 서로 다른 segment가 모두 `frame_000`을 사용하고 같은 output root에 저장
- 결과: 다른 dataset의 작업 라벨 덮어쓰기
- 예방: output을 `<workspace>/<dataset_id>/.../<frame_id>.json`으로 namespace하고 dataset ID/fingerprint를 안정적으로 계산
- 사용자 동작: dataset open summary에서 실제 작업 경로 확인

### R23. 미저장 calibration preview에서 라벨 편집

- 발생: 사용자가 임시 보정값으로 point를 맞춘 뒤 box를 편집하고 calibration preview를 reset
- 결과: box와 최종 point 정렬이 달라져 편집 근거가 사라짐
- 예방: calibration dirty/preview 상태에서는 annotation 편집을 잠그고 save-as/apply 또는 reset 후에만 재개
- 사용자 동작: `보정 미확정` banner와 적용/저장/취소 선택 제공

## P1 — 첫 사용자 테스트 전에 해결할 위험

### R11. 우발적인 box 생성·삭제

- 예방: 선택 모드와 생성 모드 분리, N으로 생성, Esc 취소, Delete는 undo 가능
- UX: 저장 전 added/modified/deleted 개수 표시

### R12. 비정상 종료 시 현재 frame 편집 손실

- 예방: 명시 저장과 별도로 30초 주기 recovery snapshot, 정상 저장 후 정리
- UX: 다음 실행에서 복구/무시/비교 선택

### R13. 렌더링 지연과 메모리 급증

- 발생: 원본·병합·각 view·prefetch가 배열을 중복 복사
- 예방: immutable 원본 공유, 표시 index만 별도 보관, cache를 frame 수가 아닌 MB로 제한
- UX: 품질 preset, 실제 표시 포인트 수, loading/cancel 표시

### R14. Intensity/return/NLZ 오해

- 발생: 현재 intensity 최대값 11328을 0~1로 가정하거나 return2/NLZ를 무조건 제거
- 예방: robust percentile 정규화, return 및 NLZ layer toggle, 원본 배열 보존
- UX: 색상 기준과 filter 상태를 legend에 표시

### R15. 일부 sensor 파일 손상 또는 누락

- 예방: frame 전체를 죽이지 않고 sensor 단위 오류로 격리
- UX: 누락 sensor badge, 재시도, 해당 frame 건너뛰기 제공

### R16. Autosave 실패로 navigation 막힘

- 예방: 이동 전에 저장을 완료하고 실패하면 현재 frame 유지
- UX: 경로·원인·save-as 버튼을 한 대화상자에 제공

### R17. 숫자 입력과 단축키 충돌

- 예방: text field focus에서 전역 문자/삭제 단축키 비활성화, 숫자 입력을 한 undo transaction으로 묶음
- UX: 잘못된 값은 필드 옆에 표시하고 마지막 정상값 유지

### R18. Projection을 정답처럼 오해

- 발생: rolling shutter, sensor timestamp 차이, motion compensation 부재
- 예방: projection 품질 상태와 적용/미적용 보정 요소 기록
- UX: `정확/근사/비활성` badge와 tooltip 제공

### R19. 포맷 export의 암묵적 변환

- 예방: class/좌표/z 기준/누락 field를 export report에 명시
- UX: export 전에 대상 파일 수, overwrite 여부, 경고를 preview

### R20. 손상된 working label의 조용한 fallback

- 발생: 작업 JSON parse/schema 실패 후 source label을 자동으로 다시 표시
- 결과: 이전 수정이 사라졌다는 사실을 모른 채 새 작업으로 덮어쓸 수 있음
- 예방: working file이 존재하면 실패를 명시하고 `.bak`/recovery/source를 후보로 제공
- UX: 각 후보의 저장 시각·revision·object 수를 비교한 뒤 사용자가 선택

### R21. Schema version 변경

- 발생: 새 앱이 구버전 working label을 현재 형식으로 바로 overwrite
- 결과: 되돌릴 수 없는 metadata 손실
- 예방: 명시적 migration, 원본 백업, migration round-trip 테스트
- UX: 변환 전후 버전과 백업 경로를 표시

### R22. 잘못된 dataset root와 과도한 scan

- 발생: ZIP과 여러 dataset 폴더가 함께 있는 `incoming/` 상위 폴더를 열거나 모든 frame metadata를 시작 시 전부 parse
- 결과: adapter 오인식, 긴 시작 시간, 불필요한 메모리 사용
- 예방: root signature로 후보를 찾고 frame metadata/label/point는 필요할 때 lazy load
- UX: 상위 폴더면 인식된 dataset 후보 목록을 보여주고 ZIP은 직접 열지 않고 압축 해제를 안내

## P2 — 후속 개선

- 자동 calibration 추정 및 정렬 품질 metric
- 프레임 보간과 tracking workflow
- 여러 카메라 동시 mosaic
- 자동 업데이트와 코드 서명
- 협업 서버와 실제 다중 사용자 locking

## 구현 Gate

### Gate A — 데이터 계약

- NxC loader, frame/device adapter, sync, source frame 판정 테스트 통과
- 현재 샘플 198 frame scan과 frame 000 label import 통과

### Gate B — 안전한 편집

- undo/redo, atomic save, recovery, source 비변경 hash 테스트 통과
- 빠른 navigation stale-result 테스트 통과

### Gate C — 사용자 테스트

- dataset open validation, create mode, sensor/calibration badge, 진행률 동작
- 손상/누락/권한 오류에서 사용자가 복구 경로를 이해할 수 있음

### Gate D — 배포

- Python 미설치 clean Windows에서 OpenGL, 한글/공백 경로, 저장·복구 smoke test 통과
