# LiDAR Label Tool 실사용 테스트 매뉴얼

이 문서는 실제 라벨링을 시작하기 전에 사용자가 그대로 따라 해보고 피드백을 남기기 위한 절차이다. 기능 설명은 `docs/USER_MANUAL.md`, 데이터 품질 점검은 `docs/18_PREFLIGHT_AND_QA.md`를 함께 참고한다.

## 1. 테스트 목표

이번 테스트에서는 다음을 확인한다.

- 데이터셋 폴더를 헷갈리지 않고 열 수 있는가
- 기존 라벨이 있으면 먼저 표시되고, 없으면 빈 라벨로 새 작업을 시작할 수 있는가
- 객체 선택, 새 박스 생성, 이동, 크기 변경, yaw 변경, height 변경이 자연스러운가
- 다음 프레임 이동 시 새로 만든 박스를 이어받는 흐름이 실제 작업에 맞는가
- 3D, Object Detail 3D, BEV, side, camera projection이 같은 객체를 일관되게 보여주는가
- 저장, 복구 snapshot, session lock, export가 source label을 건드리지 않고 동작하는가
- 느린 부분, 불편한 버튼, 헷갈리는 문구가 있는가

## 2. 테스트 전에 지킬 것

가능하면 원본 데이터셋을 바로 쓰지 말고 복사본으로 시험한다. 작업 라벨은 다음 위치에 생성된다.

```text
<dataset>\annotations\lidar_label_tool\
```

원본 source label은 덮어쓰지 않는다. 그래도 첫 테스트에서는 복사본을 쓰는 편이 마음이 편하다. 도구도 사람도 실수할 수 있으니까, 여긴 안전벨트를 매는 구간이다.

데이터셋 폴더를 선택할 때는 `dataset.json`이 직접 들어 있는 폴더를 선택한다. 예를 들면 다음 위치이다.

```text
C:\Users\USER\Desktop\Labelling_tool\local_data\incoming\merged_device_full
```

`local_data`, `incoming`, ZIP 파일, 또는 한 단계 위 폴더를 선택하면 안 된다.

## 3. 실행 전 사전검수

PowerShell에서 프로젝트 폴더로 이동한다.

```powershell
cd C:\Users\USER\Desktop\Labelling_tool
```

먼저 preflight를 실행한다.

```powershell
.\.venv\Scripts\lidar-label-tool.exe preflight `
  .\local_data\incoming\merged_device_full
```

JSON으로 저장해서 피드백에 첨부하고 싶으면 다음처럼 실행한다.

```powershell
.\.venv\Scripts\lidar-label-tool.exe preflight `
  .\local_data\incoming\merged_device_full --json
```

확인할 내용:

- `Frames`가 예상 frame 수와 맞는가
- `LiDARs`에 `MERGED`가 표시되는가
- camera 목록이 예상과 맞는가
- `errors=0`인지 확인한다
- warning이 있다면 어떤 frame, 어떤 sensor인지 적어 둔다

종료 코드 의미는 다음과 같다.

| 종료 코드 | 의미 |
|---|---|
| 0 | error와 warning 없음 |
| 1 | warning 있음, label 작업은 가능할 수 있음 |
| 2 | error 있음, 열리더라도 일부 데이터가 깨졌을 수 있음 |

## 4. GUI 실행

가장 쉬운 방법은 다음 파일을 더블클릭하는 것이다.

```text
C:\Users\USER\Desktop\Labelling_tool\run_merged_sample.bat
```

다른 데이터셋을 고르려면 다음 파일을 더블클릭한다.

```text
C:\Users\USER\Desktop\Labelling_tool\run_gui.bat
```

PowerShell에서 직접 열 수도 있다.

```powershell
.\.venv\Scripts\lidar-label-tool.exe gui `
  .\local_data\incoming\merged_device_full
```

데이터셋 확인 창이 뜨면 다음을 본다.

- frame 수
- LiDAR/camera 목록
- 원본 라벨 존재 여부
- 작업 라벨 저장 위치
- warning/error 요약

내용이 맞으면 계속 진행한다. 같은 데이터셋을 다른 앱이 이미 열고 있다는 session lock 경고가 나오면, 먼저 열린 프로그램을 닫은 뒤 다시 여는 것이 안전하다.

## 5. 첫 화면 확인

GUI가 열리면 다음 순서로 확인한다.

1. 우측 프레임 패널에서 현재 frame과 전체 frame 수가 보이는지 본다.
2. `LiDAR 센서`에 `MERGED · Not required` 또는 예상한 상태가 보이는지 본다.
3. 하단 상태줄에서 frame id, point 수, object 수, 저장 상태, warning 수가 보이는지 본다.
4. 기존 라벨이 있는 frame이면 3D 박스가 보이는지 본다.
5. 라벨이 없는 frame이면 객체 목록이 비어 있어도 앱이 정상 실행되는지 본다.

문제가 있으면 피드백에 다음을 적는다.

- dataset 경로
- frame id
- camera id 또는 sensor id
- 화면에 보인 warning/error 문구
- 스크린샷

## 6. 객체 선택 테스트

다음 세 가지 방법으로 같은 객체가 선택되는지 확인한다.

1. 우측 객체 목록에서 객체 클릭
2. 전체 3D 포인트 클라우드에서 박스 클릭
3. BEV 보조 뷰를 켠 뒤 BEV 박스 클릭

정상 동작:

- 선택 객체가 노란색으로 강조된다
- Object Detail 3D가 선택 객체 주변 point를 보여준다
- camera에 선택 객체 projection이 노란색으로 보인다
- 객체 정보 패널의 ID, class, center, size, yaw가 선택 객체와 맞는다

불편하면 특히 다음을 적어 둔다.

- 선택이 너무 어렵다
- 어떤 뷰에서는 선택이 되는데 다른 뷰에서는 안 된다
- 선택 후 시점 이동이 과하다
- 선택 강조 색이나 두께가 잘 안 보인다

## 7. 표시 옵션 테스트

우측 `포인트 표시`에서 다음을 바꿔 본다.

- 색상: `센서별`, `높이`, `Intensity`, `단색`
- 크기
- 박스 선 두께
- 객체 이름·BEV 크기 표시

정상 동작:

- 포인트 색/크기 변경은 라벨 값을 바꾸지 않는다
- 박스 선 두께 변경은 화면 표시만 바꾼다
- 객체 이름표가 너무 많은 frame에서는 선택 객체 위주로 표시된다
- BEV에는 `length × width (m)`가 함께 보인다

느려지거나 화면이 복잡해지면 어떤 옵션에서 그랬는지 적는다.

## 8. 기존 박스 수정 테스트

객체 하나를 선택하고 우측 `3D 박스 편집` 값을 조금씩 바꾼다.

권장 테스트값:

- x를 `+0.1 m`
- y를 `+0.1 m`
- height를 `+0.1 m`
- yaw를 `+2 deg`

정상 동작:

- 전체 3D, Object Detail 3D, BEV, side, camera live projection이 같이 갱신된다
- 창 제목이나 상태줄에 저장되지 않은 변경 상태가 표시된다
- Ctrl+Z로 되돌아간다
- Ctrl+Y로 다시 적용된다

현재 객체 박스는 yaw 중심이다. 객체 box의 pitch/roll 저장과 편집은 아직 정식 지원 범위가 아니다.

## 9. 키보드 편집 테스트

객체를 선택한 뒤 단축키를 사용한다.

| 키 | 동작 |
|---|---|
| W / S | x 전방 / 후방 이동 |
| A / D | y 좌측 / 우측 이동 |
| Shift+W/A/S/D | 미세 이동 |
| Q / E | yaw 감소 / 증가 |
| R / F | length 증가 / 감소 |
| T / G | width 증가 / 감소 |
| Y / H | height 증가 / 감소 |
| ← / → | 이전 / 다음 frame |

우측의 `키보드 조절 간격`에서 다음 값을 바꿔 본다.

- 이동
- 미세 이동
- 크기
- 회전

정상 동작:

- 키보드로 움직여도 전체 3D와 BEV/Detail 시점이 불필요하게 초기화되지 않는다
- step 값을 크게 하면 더 크게 움직인다
- 수치 입력칸에 focus가 있을 때는 우발적인 전역 단축키가 줄어든다

## 10. BEV와 SideView 편집 테스트

우측 `보조 뷰`에서 BEV와 측면 표시를 켠다.

BEV에서 확인할 것:

- 박스 내부 또는 중심 드래그: x/y 이동
- 모서리 handle 드래그: length/width 변경
- 원형 회전 handle 드래그: yaw 변경

SideView에서 확인할 것:

- 박스 본체 수직 드래그: z 이동
- 상단/하단 handle 드래그: height 변경

정상 동작:

- 드래그 중 미리보기가 보인다
- 마우스를 놓을 때 한 번만 편집 이력에 기록된다
- Ctrl+Z 한 번으로 직전 드래그가 되돌아간다

## 11. 새 박스 생성 테스트

1. 우측 `새 박스 생성`에서 클래스를 고른다.
2. `새 박스 만들기 · BEV에서 위치 클릭` 버튼을 누른다.
3. BEV가 열리면 빈 위치에서 좌클릭 드래그한다.
4. 마우스를 놓으면 새 박스가 생성되고 선택되는지 확인한다.
5. 수치 패널이나 키보드로 z, height, yaw, 크기를 보정한다.

짧게 클릭하면 선택 class의 기본 크기로 생성된다. 생성 모드는 Esc로 취소한다.
새 박스는 클릭 위치의 point footprint에서 바닥 z를 추정해 생성된다. 그래도 박스가 위에 뜨거나 아래로 박혀 보이면 선택 후 `포인트 바닥에 맞춤` 버튼을 눌러 z를 다시 맞춘다.

현재 class 목록은 설정 파일 기반이다. GUI에서 새 class를 즉석 생성하거나 class catalog를 편집하는 기능은 아직 정식 지원하지 않는다.

## 12. 다음 프레임 이어받기 테스트

프레임 패널에서 `새로 만든 박스를 다음 프레임으로 이어가기`를 켠다.

테스트 순서:

1. frame N에서 새 박스를 하나 만든다.
2. 오른쪽 방향키 또는 `다음 ▶`으로 frame N+1로 이동한다.
3. 같은 ID의 박스가 이어지는지 확인한다.
4. frame N+1에서 위치를 조금 보정한다.
5. 다시 다음 frame으로 이동해 같은 흐름이 자연스러운지 확인한다.

정책:

- 이 도구에서 새로 만든 박스만 이어받는다
- source에서 불러온 모든 객체를 자동 복사하지 않는다
- 이전 frame으로 갈 때는 자동 복사하지 않는다
- frame 콤보로 건너뛰는 경우도 자동 복사하지 않는다

## 13. Camera projection 확인

camera 패널에서 다음 layer를 켜고 끄며 비교한다.

- 원본 카메라 2D
- 원본 LiDAR 투영 2D
- 현재 3D 박스 실시간 투영

실제 편집 확인은 `현재 3D 박스 실시간 투영`을 기준으로 본다. 원본 camera 2D와 LiDAR 3D label은 생성 방식이 달라 완전히 일치하지 않을 수 있다.

projection이 이상해 보이면 다음을 기록한다.

- camera 이름: 예를 들어 `FRONT`, `FRONT_LEFT`
- frame id
- 선택 객체 ID
- 어떤 layer에서 이상한지
- 긴 선, 화면 밖 접힘, 박스 offset, 크기 불일치 중 무엇인지
- 차량이 움직이는 객체인지 정지 객체인지

## 14. 저장과 재로드 테스트

작업 중 Ctrl+S를 눌러 저장한다.

저장 위치:

```text
<dataset>\annotations\lidar_label_tool\<frame_id>.json
```

확인 순서:

1. 객체 하나의 ID, class, x/y/z, yaw를 기록한다.
2. Ctrl+S로 저장한다.
3. 다른 frame으로 갔다가 돌아온다.
4. 값이 유지되는지 확인한다.
5. 앱을 닫았다가 다시 열어도 유지되는지 확인한다.

정상 저장에 성공하면 해당 frame의 recovery snapshot은 삭제된다.

## 15. 복구 snapshot 확인

일반 작업에서는 앱이 비정상 종료되거나 저장하지 못했을 때를 대비해 recovery snapshot을 만든다.

위치:

```text
<dataset>\annotations\lidar_label_tool\.recovery\<frame_id>.recovery.json
```

다음 실행에서 저장된 작업 JSON보다 새로운 recovery가 있으면 앱이 자동 복원하지 않고 사용자에게 선택을 물어본다.

- 복구본 복원
- 이번 실행에서 무시
- 복구본 삭제

복구 관련 피드백은 “어떤 선택지를 눌렀는지”와 “선택 후 dirty 상태가 맞았는지”를 함께 적어 준다.

## 16. 작업 통계 확인

source label 기준 통계:

```powershell
.\.venv\Scripts\lidar-label-tool.exe stats `
  .\local_data\incoming\merged_device_full
```

working label 기준 통계:

```powershell
.\.venv\Scripts\lidar-label-tool.exe stats `
  .\local_data\incoming\merged_device_full --working
```

확인할 내용:

- frame 수
- object 수
- class별 object 수
- working label 수
- recovery snapshot 수

## 17. Export 테스트

일반 저장은 export를 자동 실행하지 않는다. export는 명시적으로 실행한다.

내부 JSON export:

```powershell
.\.venv\Scripts\lidar-label-tool.exe export `
  .\local_data\incoming\merged_device_full `
  --format lidar_label_json `
  --output .\local_data\exports\lidar_label_json
```

CenterPoint 중간 JSON export:

```powershell
.\.venv\Scripts\lidar-label-tool.exe export `
  .\local_data\incoming\merged_device_full `
  --format centerpoint_intermediate_json `
  --output .\local_data\exports\centerpoint_intermediate_json
```

`centerpoint_intermediate_json`은 학습 포맷 변환 전 중간 JSON이다. 공식 CenterPoint/OpenPCDet 학습 포맷이라고 간주하면 안 된다.

## 18. 30분 실사용 추천 루틴

빠르게 검수하려면 다음 순서로 진행한다.

1. preflight 실행
2. GUI 실행
3. 첫 frame에서 기존 객체 3개 선택
4. camera layer를 바꿔 projection 확인
5. point 색/크기/박스 두께 변경
6. 객체 하나를 키보드로 이동 후 Undo
7. BEV에서 객체 하나 resize 후 Undo
8. SideView에서 height 변경 후 Undo
9. 새 박스 하나 생성
10. 다음 frame으로 이동해 이어받기 확인
11. 새 박스를 실제 위치에 보정
12. Ctrl+S 저장
13. 앱 재시작 후 저장값 확인
14. stats --working 실행
15. 문제가 있던 frame과 동작을 피드백 양식에 기록

## 19. 피드백 양식

문제를 발견하면 아래 형식으로 적어 주면 바로 재현하기 쉽다.

```text
[문제 제목]

데이터셋:
frame id:
camera id:
LiDAR sensor:
객체 ID:

실행한 동작:
예상한 결과:
실제 결과:

재현 빈도:
- 항상 / 가끔 / 한 번만

화면 설정:
- point color:
- point size:
- box line width:
- BEV on/off:
- side on/off:
- camera layer:

첨부:
- 스크린샷:
- preflight 결과:
- stats 결과:
```

UI가 불편한 경우는 버그가 아니어도 적어 준다.

```text
[사용성 피드백]

어떤 작업 중이었는지:
헷갈린 버튼/문구:
원하는 동작:
현재 동작:
중요도:
- 높음 / 중간 / 낮음
```

## 20. 현재 알고 있는 제한

- 객체 box의 pitch/roll 저장·편집은 아직 정식 지원하지 않는다.
- GUI에서 class catalog를 새로 만들거나 rename하는 기능은 아직 없다.
- GUI export 대화상자는 아직 없고 CLI export를 사용한다.
- source-compatible export는 아직 없다.
- camera projection은 calibration geometry 확인용이며 rolling shutter, sensor timestamp 차이, motion compensation은 아직 반영하지 않는다.
- Windows portable build 절차는 준비되어 있지만 clean PC 최종 인증은 별도 검증이 필요하다.
