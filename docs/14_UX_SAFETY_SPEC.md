# 사용자 편의·안전 명세

## 1. 데이터셋 열기

폴더를 선택하면 바로 무거운 화면을 띄우지 않고 짧은 validation summary를 먼저 보여준다.

`dataset.json`이 없지만 LiDAR 후보가 있는 폴더는 adapter 오류로 끝내지 않고 범용 v2 구성
화면으로 연결한다. 구성 화면은 다음 규칙을 지킨다.

- LiDAR 후보는 여러 개 선택할 수 있지만 후보마다 독립 profile을 만들고 profile당 활성 LiDAR는
  정확히 하나다.
- camera는 없음 또는 한 개만 선택한다.
- BIN point columns, coordinate frame, timestamp column/unit/clock domain을 자동 추측하지 않는다.
- 좌표 계약 확인 전에는 생성을 허용하지 않는다.
- `구성 분석`은 파일을 쓰지 않고 frame/match/unmatched/reuse/max delta를 보여준다.
- 분석 후 설정이나 원본이 바뀌면 오래된 결과를 폐기하고 재분석을 요구한다.
- `dataset.json`은 새 generation의 schema·payload·preflight 검증이 끝난 뒤 마지막에 원자 교체한다.
- 읽기 전용 원본은 별도 configuration/annotation workspace를 선택하게 한다.

- 인식된 adapter와 dataset 이름
- frame 수
- LiDAR/camera 목록과 primary sensor
- point column과 source coordinate frame
- source/working label 존재 여부
- calibration 상태
- 누락·중복·손상 파일 수
- 작업 라벨 저장 위치와 쓰기 가능 여부

치명적 오류가 없으면 `열기`, 경고가 있으면 `경고를 확인하고 열기`, 쓰기 불가면 `별도 작업 폴더 선택`을 제공한다. 대규모 scan에는 progress와 cancel이 있어야 한다.

선택 폴더에 여러 dataset 후보나 ZIP이 함께 있으면 임의로 하나를 고르지 않는다. 후보 선택 화면을 보여주고, 1차 버전에서 ZIP 직접 열기는 지원하지 않으므로 압축 해제를 안내한다. 초기 scan은 root signature와 파일 inventory만 읽고 frame의 큰 metadata/point/label은 lazy load한다.

## 2. 항상 보여야 하는 상태

| 위치 | 표시 내용 |
|---|---|
| 상단 | dataset, frame `현재/전체`, frame status, dirty/save 상태 |
| sensor bar | LiDAR/camera 활성화, 누락, coordinate frame |
| calibration badge | Not required / Applied / Missing / Invalid / Disabled |
| image header | active camera, timestamp 차이, projection 정확도 |
| 하단 status | 표시/원본 포인트 수, filter, 작업 파일 경로, 최근 메시지 |

색상만으로 상태를 전달하지 않고 icon, text, tooltip을 함께 사용한다.

## 3. Box 생성과 편집

- 기본은 선택 모드이며 빈 공간 클릭으로 box를 만들지 않는다.
- `Add` 버튼 또는 N으로 생성 모드에 들어간다.
- click-drag 중 크기와 yaw를 미리 표시하고 Esc로 취소한다.
- 생성 직후 object list와 수치 패널에 focus한다.
- Delete는 즉시 반영하되 undo 가능하므로 반복 확인 대화상자를 띄우지 않는다.
- class, 좌표, 크기 변경은 하나의 사용자 동작 단위로 undo stack에 기록한다.
- 선택 box는 모든 view에서 text label과 강조 edge로 식별한다.

## 4. Frame workflow

각 frame은 다음 상태 중 하나를 가진다.

- `unvisited`
- `in_progress`
- `reviewed`
- `skipped`

frame을 보기만 하면 `unvisited`를 유지하고, 첫 편집 시 `in_progress`가 된다. 사용자가 명시적으로 완료 표시하면 `reviewed`가 된다. 단순히 다음 frame으로 이동했다고 자동 완료 처리하지 않는다.

수동 프레임 연결은 기준 객체 snapshot을 기억한 뒤 현재 frame에 같은 ID로 복사하거나 선택
객체의 ID를 연결하는 편집이다. 중복 ID, 서로 다른 클래스의 연결, profile/LiDAR 좌표계가 다른
연결을 막는다. 위치·크기·원본 metadata와 이전 ID 이력을 보존하고 현재 frame의 Undo·저장·복구
경로를 사용한다. frame 로드 중에는 연결을 비활성화하며 로드 실패 시 프레임 표시도 기존
화면으로 복원한다.

분할 폴더 간 객체 가져오기는 이전 작업 JSON 하나의 객체 목록을 미리 보여준 뒤 선택한
객체들을 현재 frame에 추가한다. 추가/중복 ID 건너뜀 개수를 표시하고, 기존 박스를 덮어쓰지 않는다.
LiDAR/reference frame/좌표 계약 불일치 또는 대상에 없는 class는 적용을 막는다. 취소·손상
파일·미리보기 후 source hash/현재 frame 변경 시 현재 라벨을 보존한다. frame 로드 중에는
가져오기 버튼을 비활성화한다. 전체 가져오기는 단일 Undo이며 대상 frame의 기존 원자 저장·복구
경로만 사용한다. 좌표를 자동 예측하지 않으므로 새 프레임에서 박스 위치를 조정하도록 안내한다.

선택 객체의 다음 frame 추적은 별도 opt-in 시험 기능이다. 추적 실패·모호한 후보·기존 대상
라벨에는 자동 이동을 적용하지 않고 이유를 보여준다. 정상 이어받기 이후 이동만 별도의 Undo로
취소할 수 있다. 자동 z는 포인트 이동량 기준이며 지면에 붙인다고 가정하지 않는다. 지면 보정은
객체 ID별로 켜고 끄며 기본 OFF다. 차량에서 켠 지면 설정을 새로 선택한 표지판에 적용하지 않는다.
지면 추정은 객체 밖의 주변 지면 지지도 필요하며 근거가 부족하면 기존 z를 유지한다.

frame panel은 전체/검토 완료/수정됨/오류/건너뜀 개수와 빠른 필터를 제공한다. `다음 미검토 frame` 이동 버튼을 둔다.

## 5. 저장과 복구

- Ctrl+S: 작업 라벨 명시 저장
- frame 이동: dirty일 때 autosave 후 성공해야 이동
- 30초마다 recovery snapshot 작성
- recovery는 dirty일 때만 `<annotation workspace>/.recovery/`에 작성
- 정상 저장 후 해당 snapshot 정리
- 종료 시 dirty이면 저장/버리기/취소
- 충돌 감지 시 reload/save-as/cancel, 무조건 overwrite 버튼은 고급 선택으로 분리
- 현재 source 파일은 어떤 경우에도 autosave로 덮어쓰지 않음
- session lock에는 dataset ID, host, PID, 시작 시각을 기록하고 stale lock은 확인 후 회수 가능
- 손상 working label은 source로 자동 fallback하지 않고 `.bak`/recovery/source 후보 비교 화면을 표시
- 구버전 label은 백업 후 명시적으로 migration하고 결과를 새 revision으로 저장

사용자가 저장 위치를 헷갈리지 않도록 status bar와 저장 완료 toast에 실제 경로를 표시한다.

## 6. Calibration UX

- Auto가 sensor별 적용 필요 여부를 판정하고 이유를 표시한다.
- global toggle과 sensor별 상태를 구분한다.
- 이미 reference frame인 데이터에는 `Not required`를 표시한다.
- LiDAR transform과 camera projection을 분리해 표시하여 현재 샘플에서 LiDAR ON/OFF가 동일하게 보이는 이유를 설명한다.
- 수동 조정은 annotation 편집과 별도 dirty/undo/reset/save 상태를 사용한다.
- calibration preview가 dirty인 동안 annotation box 편집을 잠그며, 보정을 save/apply 또는 reset해야 다시 편집할 수 있다.
- 저장은 `calibration.adjusted.json`에 save-as하고 원본은 유지한다.
- active calibration을 바꾸면 영향받는 작업 frame 수와 재검토 경고를 보여준다.
- before/after는 동일 camera/view pose에서 비교한다.

## 7. 성능과 반응성

- scan/load/export/calibration preview는 background 작업으로 실행한다.
- GL item 생성·교체는 main thread에서만 한다.
- 빠른 navigation에서는 마지막 요청만 화면에 반영한다.
- 현재 frame은 우선 로드하고 다음 1개 frame만 prefetch한다.
- cache는 기본 512 MB 상한을 사용하고 오래된 frame부터 제거한다.
- 렌더 품질은 `Auto/High/Performance` preset을 제공한다.
- downsample은 표시만 바꾸며 저장/통계용 원본을 변경하지 않는다.

## 8. 오류 메시지

사용자 메시지는 다음 네 요소를 포함한다.

1. 무엇이 실패했는지
2. 어떤 파일/sensor/frame인지
3. 데이터가 안전한지
4. 다음에 할 수 있는 동작

세부 traceback은 로그에 남기고 일반 대화상자에는 그대로 노출하지 않는다. `로그 폴더 열기`와 `진단 정보 복사` 버튼을 제공한다.

## 9. View 편의

- 3D/BEV/side camera pose와 zoom을 frame 이동 시 유지
- frame 전환의 선택 복원/박스 이어받기는 자동 focus를 실행하지 않음
- 각 view에 reset/focus-selected 버튼
- splitter 크기와 마지막 active camera를 사용자 설정에 저장
- sensor별 색상 legend와 point size 조절
- source label, working label, live projection layer toggle
- 원본 box와 수정 box 비교 toggle

## 10. 첫 사용자 테스트 체크리스트

- [ ] 처음 보는 사용자가 2분 안에 dataset과 작업 저장 위치를 이해한다.
- [ ] 기존 label과 수정 label의 차이를 색상뿐 아니라 text로 구분한다.
- [ ] calibration이 왜 적용/미적용되었는지 sensor별로 설명된다.
- [ ] 실수로 만든/삭제한 box를 undo할 수 있다.
- [ ] 빠르게 frame을 넘겨도 point, image, label frame ID가 일치한다.
- [ ] 저장 실패·앱 crash·외부 변경 뒤에도 원본과 마지막 저장본이 안전하다.
- [ ] 표시가 느릴 때 사용자가 quality를 낮추고 작업을 계속할 수 있다.
