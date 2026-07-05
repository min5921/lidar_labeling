# 사용자 편의·안전 명세

## 1. 데이터셋 열기

폴더를 선택하면 바로 무거운 화면을 띄우지 않고 짧은 validation summary를 먼저 보여준다.

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
