# LiDAR Label Tool 사용자 매뉴얼

이 문서는 현재 개발 PC에서 샘플 데이터셋을 열고, 기존 객체를 확인·수정·저장하는 방법을 설명한다.

## 1. 현재 지원 범위

- 현재 제공된 Waymo-style `frame_000`, `frame_001` 구조
- 단일 merged `.bin`/`.pcd` LiDAR와 `.jpg/.jpeg/.png` camera image
- 기존 `laser_labels.json`, `camera_labels.json`, `projected_lidar_labels.json`
- 기존 3D 박스 수정, 새 박스 추가, 삭제, Undo/Redo, 작업 JSON 저장
- camera calibration을 이용한 현재 3D 박스 실시간 투영
- `dataset.json` 기반 `MERGED/000000.bin`, `000001.bin` 입력

현재 버전은 개발용 Python 환경이 필요하다. Python이 없는 다른 PC에서 실행하는 portable 배포본은 아직 제작 전이다.

원본 라벨 파일은 선택 사항이다. 라벨이 없으면 객체 0개의 `unvisited` 프레임으로 열리고, 새 박스를 만든 뒤 작업 JSON으로 저장할 수 있다. Camera GT와 source projected 레이어만 비어 있으며 camera calibration이 있으면 live projection은 사용할 수 있다.

객체가 하나도 없는 상태에서도 `작업 라벨 생성` 버튼 또는 Ctrl+S를 누르면 `objects: []`인 작업 JSON을 명시적으로 생성한다.

## 2. 가장 쉬운 실행 방법

전체 변환된 merged 샘플을 바로 열려면 `run_merged_sample.bat`을 더블클릭한다.

다른 데이터를 선택하려면:

1. `C:\Users\USER\Desktop\Labelling_tool` 폴더를 연다.
2. `run_gui.bat`을 더블클릭한다.
3. 폴더 선택 창에서 다음 샘플 폴더를 선택한다.

```text
C:\Users\USER\Desktop\Labelling_tool\local_data\incoming\merged_device_full
```

선택하는 폴더 바로 아래에 `dataset.json`과 `sensors`, `sync` 폴더가 있어야 한다. ZIP 파일이나 `incoming` 상위 폴더를 선택하면 안 된다. 기존 `schema.json + segment.json + frame_000` 샘플도 호환 adapter로 계속 열 수 있다.

4. 데이터셋 확인 창에서 frame 수, LiDAR/camera 목록, 좌표계, 원본 라벨, 작업 저장 폴더를 확인한다.
5. 내용이 맞으면 `예`를 눌러 연다.

작업 저장 폴더에 쓸 수 없으면 별도 작업 폴더 선택 창이 열린다. 이때 선택한 폴더 아래에 데이터셋 ID별 작업 라벨이 저장되며 원본 데이터셋은 변경하지 않는다.

## 3. PowerShell로 실행하는 방법

프로젝트 폴더에서 다음 명령을 실행한다.

```powershell
.\run_gui.bat
```

샘플 경로를 직접 지정하려면 다음 명령을 사용한다.

```powershell
.\.venv\Scripts\python.exe -m lidar_label_tool gui `
  .\local_data\incoming\merged_device_full
```

경로를 생략하면 dataset 폴더 선택 창이 열린다.

```powershell
.\.venv\Scripts\python.exe -m lidar_label_tool gui
```

## 4. `.venv`가 없을 때

이 단계는 개발 환경을 새로 구성할 때만 필요하다. Python 3.10 이상과 인터넷 연결이 필요하다.

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[gui,validation]"
```

설치가 끝나면 `run_gui.bat`을 다시 실행한다.

## 5. 화면 구성

| 위치 | 기능 |
|---|---|
| 좌측 | 전체 3D 포인트 클라우드와 3D 박스 확인 |
| 중앙 상단 | 선택 camera image와 2D/live projection |
| 중앙 하단 | 선택 박스 중심/yaw 정렬 Object Detail 3D |
| 우측 | frame, camera layer, LiDAR sensor, 포인트 표시, 객체 목록, 수치 편집 |
| 하단 상태줄 | 로드·저장 결과와 calibration 상태 |

우측 패널이 길면 마우스 휠로 아래까지 스크롤한다. 화면 사이 경계는 드래그해 크기를 바꿀 수 있다.

BEV와 측면 뷰는 우측 `보조 뷰`에서 필요할 때 켠다. 새 박스 생성 모드에 들어가면 BEV가 자동으로 열린다.

## 6. 먼저 확인할 항목

데이터를 연 뒤 다음을 확인한다.

1. 우측 `프레임`에 현재/전체 frame 수가 표시되는지 확인한다.
2. 하단에 `LiDAR calibration: 불필요 (vehicle frame)`가 표시되는지 확인한다.
3. 정식 merged 데이터에서는 `LiDAR 센서`에 `MERGED · Not required` 하나가 표시되는지 확인한다.
4. `작업 저장:` 경로를 확인한다.

센서 이름 옆에는 `Not required`, `Applied`, `Missing`, `Invalid`, `Disabled`, `Load failed`, `Unknown` 중 하나가 표시된다. 일부 return만 손상된 경우 해당 센서는 `Load failed (일부 return 사용 가능)`로 표시되며 정상 return은 계속 렌더링된다. 자세한 파일 오류는 센서 항목이나 하단 상태 메시지에 마우스를 올려 확인한다.

현재 샘플의 LiDAR point는 이미 vehicle frame이다. LiDAR extrinsic을 다시 적용하면 이중 보정이 되므로 현재 버전에서는 재적용하지 않는다.

## 7. 기존 객체 선택과 확인

- 우측 객체 목록, 전체 3D 박스 또는 BEV 박스를 클릭한다.
- 선택 객체는 3D, BEV, 측면, camera에서 노란색 굵은 선과 중심점으로 표시된다.
- `선택 시 모든 뷰에서 자동 이동`을 끄면 기존 zoom을 유지할 수 있다.
- `선택 객체로 이동` 버튼으로 언제든 다시 중심을 맞출 수 있다.

camera 시야 밖의 객체는 이미지에 표시되지 않으며, 우측에 그 이유가 안내된다.

## 8. 포인트 표시 조절

`포인트 표시`에서 다음 색상 모드를 선택할 수 있다.

- 센서별: LiDAR 센서를 서로 다른 색으로 표시
- 높이: z 높이에 따라 색상 변경
- Intensity: 반사 강도에 따라 색상 변경
- 단색: 사용자가 지정한 한 색으로 표시

크기는 0.5~8.0 px 범위에서 바꿀 수 있다. 이 설정은 화면 표시만 바꾸며 원본 point와 저장 라벨에는 영향을 주지 않는다.

`박스 선 두께`는 0.5~8.0 범위에서 조절한다. 전체 3D, Object Detail 3D, camera, BEV, side의 일반 박스와 선택 강조 박스에 동시에 적용되며 저장되는 box 값에는 영향을 주지 않는다.

`객체 이름·BEV 크기 표시`를 켜면 전체 3D에 `class · ID 앞 6자리` 이름표가 표시되고, BEV에는 이름과 `length × width (m)`가 함께 표시된다. 객체의 `attributes.name`이 있으면 그 값을 우선 사용한다. 글자 겹침을 막기 위해 객체가 15개보다 많은 밀집 프레임에서는 선택 객체만 표시한다.

객체를 선택하면 Object Detail 3D가 박스 중심을 원점으로 사용하고 박스 yaw를 전방축으로 정렬한다. 기본적으로 박스 외곽 3 m까지의 활성 LiDAR point만 표시하므로 박스 안팎의 point 분포를 자세히 확인할 수 있다.

Object Detail 3D에서 사용자가 돌리거나 확대한 시점은 프레임을 이동하거나 값을 편집해도 유지된다. 새 박스를 만든 경우에만 새 객체를 보기 좋은 기본 시점으로 초기화한다.

## 9. 기존 박스 수정

1. 객체를 선택한다.
2. 우측 `3D 박스 편집`에서 값을 바꾼다.
3. Enter를 누르거나 다른 입력칸을 클릭해 적용한다.

값의 의미:

| 값 | 의미 |
|---|---|
| x | vehicle 기준 전방 위치(m) |
| y | vehicle 기준 좌측 위치(m) |
| z | 박스 기하 중심 높이(m) |
| length | 박스 전후 길이(m) |
| width | 박스 좌우 폭(m) |
| height | 박스 높이(m) |
| Yaw | z축 회전각(degree). JSON에는 radian으로 저장 |

값을 수정하면 네 뷰와 camera live projection이 즉시 갱신되고 `저장되지 않은 변경 있음`이 표시된다. 창 제목 앞에도 `*`가 붙는다.

BEV에서 객체를 선택하면 중심점, 네 모서리 사각 handle, 전방축 바깥의 원형 회전 handle이 표시된다.

- 중심이나 박스 내부 드래그: x/y 이동
- 모서리 handle 드래그: 반대 모서리를 고정하고 length/width 및 중심 조정
- 원형 회전 handle 드래그: 중심에서 handle 방향으로 yaw 조정

드래그 중에는 노란 점선 미리보기가 표시되고 마우스를 놓을 때 한 번만 적용된다. 최소 length/width는 0.05 m이며 z, height, class, ID와 기타 속성은 유지된다. 각 동작은 Ctrl+Z 한 번으로 되돌릴 수 있다. 생성 모드가 켜져 있을 때는 기존 박스 편집 대신 새 박스 생성이 동작한다.

SideView를 켜면 선택 박스 중심과 상·하단 사각 handle이 표시된다. 박스 본체를 수직으로 드래그하면 z만 이동하고, 상단 또는 하단 handle을 드래그하면 반대 면을 고정한 채 중심 z와 height가 함께 조정된다. 최소 height는 0.05 m이며 x/y, length/width, yaw는 유지된다.

## 10. 새 박스 추가

1. 우측 상단의 `새 박스 생성`에서 클래스를 선택한다.
2. `새 박스 만들기 · BEV에서 위치 클릭` 버튼을 누른다.
3. BEV 보조 뷰가 자동으로 열리면 빈 공간에서 좌클릭 드래그하여 length와 width를 정한다.
4. 짧게 클릭하면 선택한 클래스의 기본 크기로 생성된다.
5. 생성된 박스가 선택되면 수치 패널에서 z, 크기, yaw를 조정한다.

생성 위치의 z는 기본 박스가 바닥 z=0에 놓이도록 클래스 기본 높이의 절반으로 설정된다. 드래그 중 노란 점선 미리보기가 표시되며 생성 후 Q/E 또는 Yaw 수치로 회전한다.

생성 모드를 취소하려면 Esc를 누른다.

프레임 패널의 `새로 만든 박스를 다음 프레임으로 이어가기`가 켜져 있으면 이 도구에서 생성한 박스만 바로 다음 프레임으로 복사된다. 같은 object ID를 유지하므로 다음 프레임에서 위치와 크기를 조금씩 보정하며 추적할 수 있다. 원본에서 불러온 모든 객체를 복제하지 않으며, 이전 프레임이나 프레임 콤보로 건너뛸 때는 자동 복사하지 않는다.

## 11. 삭제와 되돌리기

- 객체 삭제: 객체 선택 후 `삭제` 또는 Delete
- 되돌리기: `Undo` 또는 Ctrl+Z
- 다시 실행: `Redo` 또는 Ctrl+Y

삭제 확인 창은 반복 작업을 방해하지 않도록 표시하지 않는다. 잘못 삭제했으면 저장 전에 바로 Undo한다.

## 12. 주요 단축키

| 키 | 동작 |
|---|---|
| ← / → | 이전 / 다음 frame |
| Ctrl+S | 저장 |
| Ctrl+Z / Ctrl+Y | Undo / Redo |
| N / Esc | 새 박스 생성 모드 / 취소 |
| Delete | 선택 객체 삭제 |
| 1 / 2 / 3 / 4 | Car / Pedestrian / Cyclist / Sign |
| W / S | x 전방 / 후방 이동 |
| A / D | y 좌측 / 우측 이동 |
| Shift+W/A/S/D | x/y 미세 이동 |
| Q / E | yaw 감소 / 증가 |
| R / F | length 증가 / 감소 |
| T / G | width 증가 / 감소 |
| Y / H | height 증가 / 감소 |

수치 입력칸이나 클래스 콤보에 focus가 있을 때는 우발 편집을 막기 위해 일부 전역 단축키가 동작하지 않는다. 객체 목록에 focus가 있어도 편집 단축키는 사용할 수 있다.

## 13. Camera 레이어 이해하기

- 원본 카메라 2D(주황): camera에서 독립적으로 작성된 2D GT
- 원본 LiDAR 투영 2D(청록): source 데이터에 포함된 projected label
- 현재 3D 박스 실시간 투영(초록): 현재 작업 중인 3D box를 camera calibration으로 계산한 결과
- 선택 객체(노랑): 현재 선택된 3D box의 투영

Camera GT와 LiDAR 3D 객체는 ID와 생성 방식이 다르므로 완전히 겹치지 않을 수 있다. 수정 결과를 확인할 때는 기본 ON인 `현재 3D 박스 실시간 투영`을 기준으로 본다.

현재 projection은 calibration geometry를 검증하는 기능이다. sensor timestamp 차이, rolling shutter, motion compensation은 아직 반영하지 않으므로 움직이는 객체에서는 오차가 날 수 있다.

현재 작업 투영은 camera near plane과 이미지 경계로 clipping한다. 기존 Waymo 객체는 `camera_synced_box`에 사용자의 편집 delta를 반영한다. 특히 옆 카메라는 distortion 적용 전에 undistorted pinhole 시야각을 검사하여, 시야 밖 좌표가 distortion 다항식 때문에 화면 안으로 다시 접혀 들어오는 잘못된 긴 선을 차단한다.

## 14. Device 중심 번호형 데이터

frame별 폴더 없이 다음처럼 넣을 수 있다.

```text
dataset/
├─ dataset.json
├─ sensors/lidar/MERGED/frames/000000.bin
├─ sensors/lidar/MERGED/frames/000001.bin
├─ sensors/camera/FRONT/images/0000.jpg
├─ sync/frames.jsonl
└─ calibration/calibration.json
```

모든 센서가 같은 `0000` 번호를 사용하면 `dataset.json`의 synchronization mode를 `exact_stem`으로 지정한다. 센서별 번호가 다르면 `index`와 `sync/frames.jsonl`을 사용한다. 자세한 manifest 예시는 `docs/11_DEVICE_CENTRIC_INPUT.md`에 있다.

원본 sensor-local LiDAR는 먼저 calibration을 적용해 `MERGED` 파일로 만든다. 라벨링 GUI에는 reference frame이 확정된 MERGED 파일만 넣는다.

## 15. 저장과 재확인

저장 버튼 또는 Ctrl+S를 사용한다. 다음 frame으로 이동할 때도 변경 사항이 있으면 먼저 자동 저장된다.

작업 파일 위치:

```text
<dataset>\annotations\lidar_label_tool\<frame_id>.json
```

두 번째 저장부터는 직전 작업 파일이 다음 경로에 백업된다.

```text
<dataset>\annotations\lidar_label_tool\<frame_id>.json.bak
```

원본 파일인 `<frame>\labels\*.json`은 변경하지 않는다.

저장 확인 절차:

1. 객체의 x 값을 기록한다.
2. x를 0.1 m 변경하고 Ctrl+S를 누른다.
3. 다른 frame으로 이동했다가 원래 frame으로 돌아온다.
4. 변경한 값과 object ID가 유지되는지 확인한다.
5. 필요하면 Ctrl+Z로 원래 값으로 되돌린 뒤 다시 저장한다.

## 16. 안전하게 첫 실행을 시험하는 순서

1. sample dataset을 연다.
2. frame 000에서 객체 하나를 선택한다.
3. 포인트 색상을 `Intensity`로 바꿔 본다.
4. x 값을 0.1 m 바꾸고 네 뷰가 같이 움직이는지 확인한다.
5. Ctrl+Z로 원래 값으로 되돌아오는지 확인한다.
6. 새 박스 하나를 만든 뒤 Delete하고 Ctrl+Z로 복구한다.
7. 최종 상태가 원래와 같다면 저장하지 않고 종료해도 된다.

현재 설정에서는 미저장 변경이 남아 있으면 종료 시 자동 저장된다. 시험 변경을 남기지 않으려면 종료 전에 Undo로 원상 복구한다.

## 17. 문제 해결

### 폴더를 열 수 없다고 나오는 경우

- ZIP을 먼저 압축 해제한다.
- `incoming`이 아니라 `schema.json`과 `segment.json`이 직접 있는 dataset 폴더를 선택한다.
- 파일명과 폴더 구조를 임의로 바꾸지 않는다.

### 화면이 느린 경우

- 필요하지 않은 LiDAR sensor 체크를 끈다.
- 포인트 크기를 줄인다.
- `configs/default.json`의 `max_render_points`를 낮춘다.

### Camera 박스가 맞지 않는 경우

- 원본 카메라 2D와 현재 3D live projection을 혼동하지 않았는지 확인한다.
- camera가 FRONT인지 확인한다.
- 하단과 camera panel에서 보정값 적용 상태를 확인한다.
- 움직이는 객체는 시간 동기화 차이로 오차가 생길 수 있다.

### 저장 실패

- 상태줄에 표시된 경로와 오류를 확인한다.
- dataset 폴더가 읽기 전용인지 확인한다.
- 다른 앱 인스턴스가 같은 frame을 저장하고 있지 않은지 확인한다.
- 실패해도 기존 작업 JSON과 원본 source label은 보존된다.

데이터셋을 열 때 저장 가능 여부를 먼저 시험한다. 읽기 전용 데이터셋이면 안내에 따라 별도 작업 폴더를 선택한다.

### 3D 화면이 비어 있는 경우

- OpenGL driver를 확인한다.
- 원격 데스크톱 환경이면 로컬 실행으로 다시 확인한다.
- BEV와 측면에 point가 보이는지 먼저 확인한다.
- LiDAR 센서 목록에 `Load failed`, `Missing`, `Invalid`가 표시되는지 확인한다. 다른 정상 센서나 camera/label이 있으면 프레임 자체는 계속 열린다.

## 18. 아직 지원하지 않는 기능

- 원본 멀티 LiDAR 자동 calibration 추정
- 비정상 종료 recovery와 session lock
- frame reviewed/skipped workflow
- source-compatible 별도 export
- Python 미설치 PC용 portable 배포본
