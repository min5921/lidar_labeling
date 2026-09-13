# LiDAR Label Tool 사용자 매뉴얼

이 문서는 범용 v2 또는 호환 데이터셋을 열고, 기존 객체를 확인·수정·저장하는 방법을 설명한다.
실제 데이터로 한 바퀴 써보며 피드백을 남기는 절차는 `docs/19_TRIAL_RUN_MANUAL.md`를 따른다.

## 1. 현재 지원 범위

- JSON이 없는 `.bin`/`.pcd` 폴더 자동 탐색과 범용 v2 구성
- 여러 LiDAR 후보의 독립 profile, 카메라 0~1개, exact/timestamp-nearest index 생성
- profile/LiDAR별 v2 작업 라벨, 외부 workspace, 분석 후 generation 재동기화
- 기존 3D 박스 수정, 새 박스 추가, 삭제, Undo/Redo, 작업 JSON 저장
- camera calibration을 이용한 현재 3D 박스 실시간 투영
- 기존 v1 `MERGED` device-centric 입력과 Waymo-style `frame_000`, `frame_001` 호환
- 기존 `laser_labels.json`, `camera_labels.json`, `projected_lidar_labels.json` 호환

현재 실험실 운영본은 Windows와 Linux 모두 소스 가상환경에서 실행한다. 각 PC에는 Python 3.10
이상 64-bit가 필요하며 새 Windows PC에는 python.org 공식 Python 3.12 64-bit를 권장한다.
Conda Python만으로 Windows `.venv`를 만들지 않는다. ROS2, MCAP SDK, PySide6 등을 사용자가
따로 찾아 설치할 필요는 없다.
`requirements-lock.txt`와 OS별 setup 스크립트가 필요한 Python package를 프로젝트 가상환경에
설치한다.

원본 라벨 파일은 선택 사항이다. 라벨이 없으면 객체 0개의 `unvisited` 프레임으로 열리고, 새 박스를 만든 뒤 작업 JSON으로 저장할 수 있다. Camera GT와 source projected 레이어만 비어 있으며 camera calibration이 있으면 live projection은 사용할 수 있다.

객체가 하나도 없는 상태에서도 `작업 라벨 생성` 버튼 또는 Ctrl+S를 누르면 `objects: []`인 작업 JSON을 명시적으로 생성한다.

## 2. 가장 쉬운 실행 방법

처음 받은 PC에서는 먼저 한 번만 환경을 설치한다.

Windows:

```text
launchers\windows\setup_windows.bat
```

설치가 끝난 뒤 다음 파일을 더블클릭한다.

```text
launchers\windows\run_windows.bat
```

Linux:

```bash
chmod +x launchers/linux/setup_linux.sh launchers/linux/run_linux.sh
./launchers/linux/setup_linux.sh
./launchers/linux/run_linux.sh
```

첫 화면에서 데이터 폴더 열기, 범용 v2 재동기화, Preflight, 통계, export를 선택한다. 특정
one_chip 원본 변환·검증은 `고급 도구 — one_chip 레거시 전용`에 분리되어 있다. 사용자 설정은
Windows의 AppData 또는 Linux의 XDG 사용자 경로에 저장된다.

다른 데이터를 선택하려면:

1. Git으로 받은 프로젝트 폴더를 연다.
2. `launchers/windows/run_windows.bat`을 더블클릭한다.
3. 폴더 선택 창에서 실제 원본 또는 구성 폴더를 선택한다.

기존 데이터셋은 선택하는 폴더 바로 아래에 `dataset.json`이 있어야 한다. `dataset.json`이 없는
일반 LiDAR 폴더를 선택하면 범용 구성 화면이 열리며, point columns·좌표계·선택적 camera와
timestamp를 입력한다. `구성 분석`에서 frame 수와 camera 매칭 QA를 확인한 다음
`검증 결과로 생성`을 눌러야 프로그램이 필요한 JSON/index를 생성한다. 기존
`schema.json + segment.json + frame_000` 샘플도 호환 adapter로 계속 열 수 있다. 자세한 구성법은
[`33_GENERIC_DATASET_SETUP_GUIDE.md`](33_GENERIC_DATASET_SETUP_GUIDE.md)를 따른다.

4. 범용 v2는 profile 선택 창에서 이번 세션의 LiDAR 하나를 선택한다.
5. 데이터셋 확인 창에서 frame 수, LiDAR/camera 목록, 좌표계, 원본 라벨, 작업 저장 폴더를 확인한다.
6. 내용이 맞으면 `예`를 눌러 연다.

`launchers/legacy/run_merged_sample.bat`은 예전 MERGED 샘플 전용이므로 일반 데이터에는 사용하지
않는다.

작업 저장 폴더에 쓸 수 없으면 별도 작업 폴더 선택 창이 열린다. 이때 선택한 폴더 아래에 데이터셋 ID별 작업 라벨이 저장되며 원본 데이터셋은 변경하지 않는다.

## 3. 명령줄에서 실행하는 방법

프로젝트 폴더에서 다음 명령을 실행한다.

```powershell
.\launchers\windows\run_windows.bat
```

데이터 경로를 직접 지정하려면 다음 명령을 사용한다.

```powershell
.\.venv\Scripts\python.exe -m lidar_label_tool gui `
  "D:\data\my_dataset"
```

경로를 생략하면 통합 작업 선택 화면이 열린다.

```powershell
.\.venv\Scripts\python.exe -m lidar_label_tool gui
```

Linux에서 데이터셋 경로를 직접 지정하려면 다음처럼 실행한다.

```bash
./launchers/linux/run_linux.sh /data/my_dataset
```

### LiDAR–카메라 calibration을 화면에서 조정하기

기존 데이터셋 adapter가 연결해 둔 LiDAR frame과 camera image를 그대로 사용하여 별도
calibration 편집기를 연다.

Windows에서는 프로젝트 폴더의 다음 파일을 더블클릭한다.

```text
launchers\windows\run_calibration.bat
```

폴더 선택창이 열리면 `dataset.json` 또는 `schema.json + segment.json`이 바로 아래에 있는
데이터셋 폴더를 선택한다. Linux에서는 `chmod +x launchers/linux/run_calibration.sh`를 한 번
실행한 뒤 `./launchers/linux/run_calibration.sh`를 사용한다.

```powershell
.\.venv\Scripts\python.exe -m lidar_label_tool calibrate `
  C:\data\my_dataset
```

범용 v2 데이터셋에서 profile을 직접 지정하려면 다음과 같이 실행한다.

```powershell
.\.venv\Scripts\python.exe -m lidar_label_tool calibrate `
  C:\data\my_dataset --profile aeva_profile
```

dataset/profile이 아직 조정본을 가리키지 않는 상태에서 저장했던 JSON을 다시 기준값으로 열려면
화면의 `기존 Calibration JSON 불러오기`를 누르거나 다음 옵션을 사용한다.

```powershell
.\.venv\Scripts\python.exe -m lidar_label_tool calibrate `
  C:\data\my_dataset --calibration C:\work\front.adjusted.json
```

- 기존 camera calibration이 있으면 해당 투영 결과를 조정 전 기준값으로 불러온다.
- calibration이 없으면 현재 이미지 크기로 `fx/fy/cx/cy` 시작값을 추정하고 extrinsic은
  identity에서 시작한다. 이 intrinsic은 편집 시작용 추정값이지 측정된 calibration이 아니다.
- X/Y/Z는 m, Roll/Pitch/Yaw는 degree이며 최종 변환은
  `T_effective = correction_delta @ T_camera_reference`로 계산한다.
- 미리보기의 camera tool frame은 `+X 전방, +Y 좌측, +Z 위`다. OpenCV optical frame의
  `+Z 전방, +X 우측, +Y 아래` 행렬은 축 변환 없이 그대로 사용하지 않는다.
- 상단 `카메라 / LiDAR` 슬라이더로 위·아래 화면 높이 비율을 조절한다. 두 화면 사이의
  분할선을 직접 드래그해도 슬라이더와 비율 표시가 함께 갱신된다.
- 아래 LiDAR 영역은 전체 3D와 BEV를 함께 표시한다. 우측 `LiDAR 기준 박스`에서 템플릿을
  고르고 생성 모드를 켠 뒤, BEV의 point cloud 위를 클릭하면 기본 크기 박스가 생기고
  드래그하면 length와 width를 직접 정할 수 있다.
- 기준 박스를 선택하면 노란색으로 강조된다. BEV의 중심/본체를 드래그해 x/y를 옮기고,
  네 모서리로 length/width를 바꾸며, 전방축 바깥 원형 handle로 yaw를 조절한다. 우측 수치
  입력으로 x/y/z/length/width/height/yaw를 정확히 고칠 수도 있다.
- 새 기준 박스의 z는 footprint 안의 LiDAR point로 바닥을 추정한다. 위치나 크기를 바꾼 뒤에는
  `포인트 바닥에 맞춤`으로 다시 계산할 수 있다.
- 기준 박스는 calibration 검증용 세션 데이터다. 원본/작업 라벨과 저장하는 calibration JSON에
  포함되지 않으며 프로그램을 닫으면 사라진다. 기존 3D 라벨은 별도 checkbox로 표시·투영할 수
  있지만 이 편집기에서는 읽기 전용이다.
- 청록은 조정 후 LiDAR 포인트, 초록은 조정 후 3D/기준 박스, 분홍 점선은 조정 전 결과다.
  선택한 기준 박스는 LiDAR와 카메라 화면 모두 노란색으로 보인다.
- 카메라의 투영 point가 작으면 `카메라 미리보기 레이어 > 투영 점 크기` 슬라이더를 조절한다.
  1~30 px 범위이며 기본값은 4 px다. 검은 외곽선은 촘촘한 point에서 그림자처럼 이어질 수 있어
  기본 OFF다. 아주 밝은 배경에서만 `투영 점 검은 외곽선`을 켠다. 이 값은 원본 LiDAR와
  3D/BEV point 크기를 바꾸지 않는다.
- `카메라 원본 이미지 표시`를 끄면 이미지 영역이 검정 배경으로 바뀌고 LiDAR point와 3D 박스
  투영만 남는다. 다시 켜면 같은 확대·이동 위치에서 원본 이미지가 즉시 복원된다.
- 여러 거리와 화면 위치의 frame을 확인한 뒤 `현재 프레임을 검증 완료로 기록`을 누른다.
  값을 다시 바꾸면 해당 camera의 검증 목록은 초기화된다.
- `조정본 Save As`는 원본 calibration을 선택할 수 없으며 기본적으로
  `calibration/adjusted/<camera>.adjusted.<시각>.json`을 제안한다.
- 저장은 임시 파일 검증 후 원자적으로 교체하고 기존 조정본이 있으면 `.json.bak` 한 개를
  남긴다. 저장만으로 dataset/profile의 활성 calibration은 바뀌지 않는다.

현재 미리보기는 pinhole `none`과 `brown_conrady` distortion을 지원한다. `fisheye`는 아직
지원하지 않는다. 이미지와 LiDAR의 timestamp 차이가 있는 v2 frame은 상태줄에 `Δt`로 표시하며,
움직이는 객체만 보고 spatial calibration을 맞추지 않는다.

## 4. `.venv`가 없을 때

`launchers/windows/setup_windows.bat` 또는 `./launchers/linux/setup_linux.sh`를 실행한다.
setup은 `.venv`를 만들고,
`requirements-lock.txt`의 정확한 버전을 설치한 뒤 프로그램과 기본 설정을 검증한다.
Conda 환경을 사용하는 방법과 Linux 시스템 package 요구사항은
`docs/31_LAB_SOURCE_SETUP.md`에 있다.

기존 `.venv`의 Python 버전이 너무 낮거나 환경이 손상된 경우 폴더를 수동 삭제하지 말고 다음
명령으로 프로젝트 내부 가상환경만 안전하게 다시 만든다.

```powershell
.\launchers\windows\setup_windows.bat -Recreate
```

데이터셋과 작업 라벨은 저장소 밖에 두므로 `.venv`를 다시 만들어도 변경되지 않는다.

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
2. 범용 v2는 선택한 profile과 활성 LiDAR 하나가 예상한 sensor/coordinate frame과 맞는지
   확인한다.
3. 다른 profile의 LiDAR가 현재 point cloud에 섞이지 않았는지 확인한다.
4. camera가 없거나 `display_only`여도 LiDAR frame 이동과 편집이 가능한지 확인한다.
5. `작업 저장:` 경로에 profile/LiDAR namespace가 포함되는지 확인한다.

센서 이름 옆에는 `Not required`, `Applied`, `Missing`, `Invalid`, `Disabled`, `Load failed`, `Unknown` 중 하나가 표시된다. 일부 return만 손상된 경우 해당 센서는 `Load failed (일부 return 사용 가능)`로 표시되며 정상 return은 계속 렌더링된다. 자세한 파일 오류는 센서 항목이나 하단 상태 메시지에 마우스를 올려 확인한다.

기존 Waymo-style 샘플의 LiDAR point는 이미 vehicle frame이다. 이 호환 샘플에 LiDAR extrinsic을
다시 적용하면 이중 보정이 되므로 재적용하지 않는다.

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

전체 3D와 위에서 보는 BEV, 측면 뷰의 시점·확대·중심도 저장 후 이전/다음 프레임으로 이동하거나
프레임을 직접 골라도 유지된다. 자동 이동 옵션이 켜져 있어도 프레임 전환 중 같은 객체를
다시 선택하는 과정에서는 자동 확대하지 않는다. 직접 객체를 선택하거나 `선택 객체로 이동`을
누르면 그 객체를 중심으로 볼 수 있다.

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

생성 위치의 z는 먼저 BEV 클릭 위치의 박스 footprint 안쪽 LiDAR point를 보고 바닥 높이를 추정해 `바닥 + height/2`로 설정한다. point가 부족하면 기존처럼 바닥 z=0에 놓이도록 클래스 기본 높이의 절반으로 설정된다. 드래그 중 노란 점선 미리보기가 표시되며 생성 후 Q/E 또는 Yaw 수치로 회전한다.

이미 만든 박스가 포인트보다 위에 떠 있거나 아래로 박혀 보이면 객체를 선택한 뒤 `B` 키 또는
`3D 박스 편집`의 `포인트 바닥에 맞춤 (B)`을 누른다. 현재 박스의 XY footprint 안쪽 point 중
낮은 z 값을 기준으로 박스 bottom을 다시 맞춘다. 크기·yaw는 유지되고 Ctrl+Z로 되돌릴 수 있다.
수치 입력 중이거나 프레임을 불러오는 중에는 B 단축키를 실행하지 않는다.

생성 모드를 취소하려면 Esc를 누른다.

프레임 패널의 `만든/가져온 박스 다음 프레임으로 이어가기`가 켜져 있으면 이 도구에서 생성한
박스와 아래 기능으로 이전 폴더에서 가져온 박스가 바로 다음 프레임으로 복사된다. 같은 object
ID를 유지하므로 다음 프레임에서 위치와 크기를 조금씩 보정하며 작업할 수 있다. 그 밖의 원본
객체를 모두 복제하지 않으며, 이전 프레임이나 프레임 콤보로 건너뛸 때는 자동 복사하지 않는다.

### 선택 객체 자동 추적과 z 보정

1. 현재 프레임에서 객체의 박스를 맞추고 선택한다.
2. 프레임 패널의 이어가기 옵션과 `선택 객체 다음 프레임 자동 추적 (시험 기능)`을 켠다.
3. `다음 ▶` 또는 `→`를 누르면 선택 객체만 다음 포인트에 맞춰 자동 이동을 시도한다.
   이 경우 선택한 원본 import 객체도 같은 ID로 이어받을 수 있다.
4. 결과를 확인하고 필요하면 수동 조정한다. Ctrl+Z 한 번이면 자동 이동 전 위치로 돌아간다.

추적은 기본 OFF다. 검색 범위는 `추적 최대 이동`에서 조절하며 기본 반경은 4 m다. 크기와 yaw는
자동으로 바꾸지 않는다. 대상에 이미 같은 ID가 있으면 기존 라벨을 유지한다. 이전/건너뛴 프레임과
폴더 경계에서는 추적하지 않는다. 포인트 부족·가림·비슷한 후보·급격한 이동 등에서는 이전 위치를
유지하고 상태줄에 이유를 표시한다. 학습형 자동 추적기가 아닌 **프레임별 작업 보조**이므로 검수가 필요하다.

z 보정은 다음처럼 선택한다.

- `추적 시 상하 위치(z)도 조정 · 크기 유지` ON: 객체 포인트의 상하 이동량을 따른다.
  표지판처럼 지면에서 떠 있는 객체도 기존 박스와 포인트의 위치 관계를 유지한다.
- 위 옵션 OFF: x/y만 추적하고 z를 유지한다.
- 차량·사람처럼 지면에 붙은 객체는 `선택 객체: 지면 높이로 z 보정`을 추가로 켠다.
  다음 프레임 추적 때 주변 지면을 추정해 박스 바닥을 맞춘다. 충분한 지면 포인트가 없으면 z는 유지한다.

지면 옵션은 **기본 OFF이며 현재 실행에서 객체 ID별로 기억**한다. 다른 객체를 선택하면 그
객체의 ON/OFF가 표시되므로 차량에서 켠 옵션이 처음 선택한 표지판으로 넘어가지 않는다.
프로그램을 재시작하면 다시 선택해야 한다. z 자동 이동 한도는 0.6 m이고 height 자체는 바꾸지 않는다.
현재 프레임에서 직접 바닥 맞춤을 하려면 기존 `B` 키를 사용한다.

`포인트 표시 > 선택 박스 안 포인트 노란색 강조`는 기본 ON이다. 전체/상세 3D, BEV, 측면에서
선택한 **3D 박스 내부** 포인트만 노란색으로 표시한다. 선택 해제 또는 옵션 OFF로 원래 색상으로
돌아가며 원본 BIN/PCD나 라벨은 변경하지 않는다. 화면에 생략된 포인트는 표시 다운샘플 설정을 따른다.

### 1000개씩 나눈 다음 폴더로 객체들 이어받기

같은 LiDAR·좌표계의 연속 데이터를 여러 폴더로 나눈 경우 사용한다. **폴더의 작업 JSON 전체를
다른 폴더에 덮어쓰는 것이 아니라 객체들만 가져오는 기능**이다.

1. 이전 폴더의 마지막 프레임에서 Ctrl+S로 저장한다.
2. 다음 데이터 폴더를 열고 첫 프레임으로 이동한다. 폴더는 사용자가 직접 열어야 한다.
3. 우측 프레임 패널에서 `이전 폴더의 객체 가져오기…`를 누른다.
4. 이전 폴더의 마지막 **작업 라벨 JSON**을 선택한다. `dataset.json`이나 `frames.jsonl`이 아니다.
   v2 기본 저장 위치는 아래와 같다. 외부 작업 폴더를 사용했다면 그곳의 작업 JSON을 고른다.

   ```text
   <이전 configuration-root>/annotations/lidar_label_tool/<profile_id>/<label_lidar_id>/<마지막 frame_id>.json
   ```

5. 객체 목록에서 이어갈 객체를 선택하고 `선택 객체 가져오기`를 누른다. 기본은 전체 선택이다.
6. 가져온 박스를 현재 포인트에 맞춰 조정한 뒤 Ctrl+S로 저장한다.
7. `만든/가져온 박스 다음 프레임으로 이어가기`를 켜 두면 이후 프레임에도 같은 ID로 이어진다.

ID·클래스·박스 크기·위치·yaw·속성은 유지한다. 위치는 이전 프레임 값이며 움직임을 자동으로
예측하지 않는다. 이미 현재 프레임에 있는 ID는 건너뛰고 기존 박스를 유지한다. 전체 가져오기는
Ctrl+Z 한 번으로 취소할 수 있고 이전 폴더의 라벨은 변경하지 않는다.

LiDAR ID/좌표계가 다르면 가져오기를 막는다. 대상에 없는 클래스는 해당 객체를 선택 해제하거나
클래스 구성을 확인해야 한다. 두 폴더의 dataset/profile ID는 달라도 되며 새 작업은 현재 폴더의
프레임과 저장 위치를 그대로 사용한다.

### 이전 프레임에 박스 복사 / 이미 만든 객체와 연결

우측 `프레임 간 객체 연결`에서 다음 순서로 작업한다.

1. 기준으로 사용할 객체를 선택하고 `선택 객체를 연결 기준으로 기억`을 누른다.
2. `←` 또는 프레임 목록으로 이전 프레임에 이동한다. 다음 프레임이나 떨어진 프레임도 가능하다.
3. 박스가 없으면 `현재 프레임에 같은 ID로 복사`를 누르고, 현재 포인트에 맞춰 위치를 조정한다.
4. 박스를 이미 따로 만들었다면 그 박스를 선택하고 `선택 객체를 기준 ID로 연결`을 누른다.
   현재 박스의 위치·크기·yaw·속성을 유지하면서 ID를 기준 객체와 같게 바꾼다.
5. 결과를 확인하고 Ctrl+S로 저장한다. 잘못 복사/연결했으면 Ctrl+Z로 되돌린다.

예를 들어 20번 프레임의 자동차를 기준으로 기억한 뒤 19번 프레임으로 가서 복사하거나,
19번에 이미 만든 자동차를 선택해 연결하면 두 프레임에서 같은 객체 ID를 사용한다.

기준 ID가 현재 프레임에 이미 있으면 그 객체를 선택해 편집한다. 같은 ID의 박스를 중복으로
만들지 않으며, 다른 클래스의 객체 연결은 먼저 클래스를 확인해야 한다. 연결은 현재 프레임에만
적용된다. 다른 프레임들의 ID를 일괄 변경하는 기능은 아니다. 변경 전 ID와 연결 이력은 작업
라벨에 기록된다. 기준은 기억한 시점의 박스이며 프로그램을 종료하면 해제된다.

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
| Space / Ctrl 단독 | z 위 / 아래 이동 |
| Shift+W/A/S/D | x/y 미세 이동 |
| Q / E | yaw 감소 / 증가 |
| R / F | length 증가 / 감소 |
| T / G | width 증가 / 감소 |
| Y / H | height 증가 / 감소 |
| B | 선택 박스 포인트 바닥에 맞춤 |

`Ctrl` 하강은 Ctrl만 눌렀다 놓은 경우에 실행된다. `Ctrl+S`, `Ctrl+Z`, `Ctrl+Y`처럼
다른 키와 조합하면 박스 높이는 바뀌지 않는다.

수치 입력칸이나 클래스 콤보에 focus가 있을 때는 우발 편집을 막기 위해 일부 전역 단축키가 동작하지 않는다. 객체 목록에 focus가 있어도 편집 단축키는 사용할 수 있다.

## 13. Camera 레이어 이해하기

- 원본 카메라 2D(주황): camera에서 독립적으로 작성된 2D GT
- 원본 LiDAR 투영 2D(청록): source 데이터에 포함된 projected label
- 현재 3D 박스 실시간 투영(초록): 현재 작업 중인 3D box를 camera calibration으로 계산한 결과
- 선택 객체(노랑): 현재 선택된 3D box의 투영

Camera GT와 LiDAR 3D 객체는 ID와 생성 방식이 다르므로 완전히 겹치지 않을 수 있다. 수정 결과를 확인할 때는 기본 ON인 `현재 3D 박스 실시간 투영`을 기준으로 본다.

현재 projection은 calibration geometry를 검증하는 기능이다. sensor timestamp 차이, rolling shutter, motion compensation은 아직 반영하지 않으므로 움직이는 객체에서는 오차가 날 수 있다.

현재 작업 투영은 camera near plane과 이미지 경계로 clipping한다. 기존 Waymo 객체는 `camera_synced_box`에 사용자의 편집 delta를 반영한다. 특히 옆 카메라는 distortion 적용 전에 undistorted pinhole 시야각을 검사하여, 시야 밖 좌표가 distortion 다항식 때문에 화면 안으로 다시 접혀 들어오는 잘못된 긴 선을 차단한다.

## 14. v1 호환 Device 중심 번호형 데이터

> 아래 `MERGED + CAM_LEFT/CAM_RIGHT`는 기존 v1/one_chip 호환 구조다. 새 범용 데이터는
> 프로그램의 v2 구성 마법사를 사용하며, 여러 LiDAR를 profile별로 분리하고 camera는 profile당
> 최대 한 개만 선택한다.

장치 구성이 고정된 데이터는 frame별 폴더 없이 다음처럼 단순하게 넣을 수 있다.

```text
dataset/
├─ dataset.json
├─ lidar/000000.bin
├─ lidar/000001.bin
├─ cam_left/000010.jpg
├─ cam_right/000009.jpg
├─ sync/frames.jsonl
└─ calibration/calibration.json
```

`MERGED`, `CAM_LEFT`, `CAM_RIGHT`는 폴더명이 아니라 `dataset.json`의 논리 sensor ID다. 기존
`sensors/lidar/MERGED/frames` 구조도 manifest의 `data_patterns`를 통해 계속 지원한다.

모든 센서가 같은 `0000` 번호를 사용하면 `dataset.json`의 synchronization mode를 `exact_stem`으로 지정한다. 센서별 번호가 다르면 `index`와 `sync/frames.jsonl`을 사용한다. 자세한 manifest 예시는 `docs/11_DEVICE_CENTRIC_INPUT.md`에 있다.

원본 sensor-local LiDAR는 먼저 calibration을 적용해 `MERGED` 파일로 만든다. 라벨링 GUI에는 reference frame이 확정된 MERGED 파일만 넣는다.

## 15. 저장과 재확인

저장 버튼 또는 Ctrl+S를 사용한다. 다음 frame으로 이동할 때도 변경 사항이 있으면 먼저 자동 저장된다.

범용 v2 작업 파일 위치:

```text
<configuration-root>\annotations\lidar_label_tool\<profile_id>\<label_lidar_id>\<frame_id>.json
```

v1 호환 작업 파일 위치:

```text
<dataset>\annotations\lidar_label_tool\<frame_id>.json
```

두 번째 저장부터는 직전 작업 파일이 다음 경로에 백업된다.

```text
<working-label-path>.bak
```

원본 파일인 `<frame>\labels\*.json`은 변경하지 않는다.

작업 라벨을 만든 뒤 source label 또는 calibration 파일의 fingerprint가 달라지면 프레임을 열 때
경고한다. 저장 시에도 다시 확인하며, 사용자가 명시적으로 계속하기 전에는 새 기준 fingerprint를
기록하지 않는다. 이 경고가 나오면 3D 박스와 camera projection을 다시 확인한다.

저장되지 않은 변경이 있으면 기본 30초 간격으로 현재 label namespace의 `.recovery`에 복구본을
원자적으로 기록한다.

```text
<label-namespace>\.recovery\<frame_id>.recovery.json
```

복구본은 정상 작업 JSON을 덮어쓰지 않는다. 다음 실행에서 저장된 작업 JSON보다 새로운 복구본이
발견되면 `복구본 복원`, `이번 실행에서 무시`, `복구본 삭제` 중 하나를 직접 선택한다. 정상 저장에
성공하면 해당 프레임의 복구본은 삭제된다.

동일 데이터셋을 다른 GUI가 열고 있으면 `.session.lock` 정보와 함께 경고한다. 먼저 열린 프로그램을
종료하고 여는 것이 안전하다. 비정상 종료로 남은 잠금은 PID 확인 후 stale 잠금으로 교체된다.

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

### 프로그램이 바로 종료되는 경우

먼저 다음 환경 검사를 실행한다.

```powershell
.\.venv\Scripts\python.exe scripts\verify_source_environment.py
```

Linux에서는 `./.venv/bin/python scripts/verify_source_environment.py`를 사용한다.
소스 실행 중 처리되지 않은 오류는 run 스크립트를 실행한 terminal에 표시된다.

Windows에서 `DLL load failed while importing QtCore/QtWidgets` 또는 `지정된 프로시저를 찾을
수 없습니다`가 표시되면 데이터셋 문제가 아니라 Python/Qt 실행 환경 문제다. 다른 PC에서
`.venv`를 복사하지 말고 다음 순서로 복구한다.

PowerShell 앞에 `(base)`가 있고 `py -3.12 --version`에서 `py 명령을 찾을 수 없습니다`가
표시되면 Conda Python만 설치된 상태다. python.org에서 공식 Python 3.12 64-bit와 Python
Launcher를 설치한 뒤 새 PowerShell을 연다. Windows setup/run 스크립트는 Conda Qt DLL 경로를
자동으로 제거하고, Conda Python으로 생성된 `.venv`를 거부한다.

```powershell
.\launchers\windows\setup_windows.bat -Repair
```

같은 오류가 계속되면 생성된 가상환경만 새로 만든다.

```powershell
.\launchers\windows\setup_windows.bat -Recreate
```

그래도 실패하면 `https://aka.ms/vc14/vc_redist.x64.exe`에서 Microsoft Visual C++ x64 runtime을
설치 또는 복구하고, `winver`에서 Windows 10 1809 이상 또는 Windows 11 x64인지 확인한다.
`-Recreate`는 `.venv`만 삭제하며 데이터셋과 작업 라벨은 변경하지 않는다.

### 명시적 라벨 export

일반 저장은 export를 자동 실행하지 않는다. 첫 화면의 `라벨 내보내기`에서 dataset과 별도
출력 폴더를 선택한다. 여러 v2 profile이 있으면 대상 LiDAR profile을 명시적으로 선택한다.
`데이터셋 검사`와 `라벨 통계`도 같은 profile 선택 절차를 사용한다.
CLI에서는 다음처럼 실행한다.

```powershell
.\.venv\Scripts\python.exe -m lidar_label_tool export <dataset> --format lidar_label_json --output <output-folder>
.\.venv\Scripts\python.exe -m lidar_label_tool export <dataset> --format centerpoint_intermediate_json --output <output-folder>
```

특정 프레임만 내보내려면 `--frame <frame_id>`를 사용하며 여러 번 지정할 수 있다. 별도 작업 폴더를
사용했다면 `--workspace <workspace-root>`를 함께 지정한다. v2는 `--profile <profile_id>`로
대상을 지정한다. 생략한 CLI는 기본 profile을 사용한다. `centerpoint_intermediate_json`은
좌표와 radian yaw를 전달하기 위한 중간 JSON이며 공식 CenterPoint/OpenPCDet 학습 포맷이라고
간주하면 안 된다.

Export는 기존 파일을 덮어쓰지 않으며, working/source label이나 generation/calibration 폴더를
출력 대상으로 사용하지 않는다. 재실행할 때는 새 폴더를 선택한다. 동시 생성된 파일도 보존하며
완성된 임시 파일을 원자적으로 공개한다. hard link를 지원하지 않는 파일시스템에서는 안전하게
실패하므로 로컬 NTFS/ext4 등의 출력 폴더를 사용한 뒤 결과를 복사한다. 배치 중 I/O 실패 시에는
이미 완료된 export 파일 수와 실패 frame을 확인한다. 이전 작업 라벨은 변경하지 않는다.

### 3D 화면이 비어 있는 경우

- OpenGL driver를 확인한다.
- 원격 데스크톱 환경이면 로컬 실행으로 다시 확인한다.
- BEV와 측면에 point가 보이는지 먼저 확인한다.
- LiDAR 센서 목록에 `Load failed`, `Missing`, `Invalid`가 표시되는지 확인한다. 다른 정상 센서나 camera/label이 있으면 프레임 자체는 계속 열린다.

## 18. 아직 지원하지 않는 기능

- 원본 멀티 LiDAR 자동 calibration 추정
- LiDAR/reference frame 변환·frame 재번호가 필요한 전체-frame migration
- v1의 안전하지 않은 dataset ID를 새 manifest와 함께 자동 치환하는 migration
- Python 미설치 PC용 단일 실행 파일 배포

## 검토 상태와 다음 미검토 이동

Frame 패널의 `검토 완료`, `건너뜀`, `작업 중` 버튼은 현재 프레임의 상태를 명시적으로 바꾼다.
박스가 존재하거나 자동 추적에 성공했다는 이유로 검토 완료가 되지는 않는다. 완료·건너뜀 뒤
객체를 편집하면 다시 작업 중이 된다. 상태 변경도 Undo/Redo가 가능하며 일반 저장을 해야
디스크에 확정된다.

`검토 상태 새로고침`으로 활성 profile 전체의 상태를 읽고 필터로 미검토/작업 중/완료/건너뜀을
좁힌다. 손상된 라벨은 오류로 표시하며 완료로 간주하지 않는다. `다음 미검토 프레임 ▶`은
현재 순서에서 다음 미검토를 찾고 끝에서 한 번 순환한다. reviewed/skipped는 제외하고,
외부에서 기준 파일이 달라진 프레임은 재검토 대상으로 잡는다. 현재 편집의 저장/취소 절차를
거치며, 중간 프레임을 건너뛰는 이 이동에는 객체 복사·자동 추적을 적용하지 않는다.

## Source JSON 내보내기

첫 화면 `라벨 내보내기`에서 `source_laser_json`을 선택하면 기존 Waymo/device-centric
`laser_labels.json`과 같은 객체 배열을 새 경로에 쓴다. Waymo protobuf나 공식 학습 데이터 전체를
생성하는 기능은 아니다. 다른 export와 마찬가지로 원본/working 파일은 수정하지 않는다.

Source 클래스 매핑은 `현재 class = TYPE`을 한 줄씩 입력한다. v2에서는 display name이 아니라
taxonomy의 stable class ID를 사용한다. 예: `car = TYPE_VEHICLE`. 명시 매핑이 없으면 v1 설정 또는
v2 taxonomy의 `source_mappings.waymo`를 사용하지만, 역매핑이 불명확하면 추측하지 않고 중단한다.

```powershell
.\.venv\Scripts\python.exe -m lidar_label_tool export <dataset> --profile <profile_id> --format source_laser_json --output <new-folder> --class-map car=TYPE_VEHICLE
```

현재 object ID·class·box가 반영되며 보존한 source의 알 수 없는 필드는 유지한다. 원본 속도/
포인트 수는 재계산하지 않는다. frame 검토 상태·revision·provenance 등 source 배열에 담지 못하는
정보는 완료 창의 세부 보고서와 CLI JSON `reports`로 안내한다. 작업 JSON도 별도로 보관한다.
배치 취소/오류는 이미 완성한 출력 파일을 보존하므로 재시도에는 새 출력 폴더를 선택한다.

## 전체 v1 작업 라벨을 v2로 이전

첫 화면 `v1 작업 라벨 → v2 이전`을 누르고 **이미 구성된 대상 v2 폴더**를 선택한다. v1 작업
라벨 JSON 폴더, v1 원본 데이터 루트, 대상 profile, 명시 class mapping(`Car = car`)을 지정한다.
분석은 파일을 쓰지 않는다. 전체 frame 수·객체 수·대상 namespace를 확인한 뒤 이전을 실행한다.

CLI도 기본은 미리보기다. 실제 실행은 같은 명령에 `--apply`를 추가한다.

```powershell
.\.venv\Scripts\python.exe -m lidar_label_tool migrate-labels-v2 <v2-config> --source-labels <v1-label-folder> --source-data <v1-data-root> --profile <profile_id> --class-map Car=car
```

- 안전한 dataset ID, 단일 LiDAR ID, reference frame, frame ID, point 상대 경로와 실제 바이트가
  일치해야 한다. 좌표 변환이나 frame 재번호를 자동 추측하지 않는다.
- 원본 JSON·`.bak`·v1 recovery는 보존한다. source/unknown metadata와 객체 ID를 유지하고
  v2 revision은 v1 revision+1로 기록한다. 카메라/보정 context는 대상 profile 기준으로 재검토한다.
- 기존 대상 namespace는 빈 폴더라도 합치거나 덮어쓰지 않는다. 대상 profile을 이미 열어서
  폴더가 생겼다면 새 profile 또는 새 외부 workspace를 선택한다.
- 전체 frame과 `.migration-report.json`을 임시 namespace에서 검증한 뒤 한 번에 활성화한다.
  동일 입력·완료 report·출력 hash가 그대로면 `already_migrated`로 쓰지 않고 끝낸다.
- 안전하지 않은 legacy dataset ID는 manifest에 동일 `metadata.legacy_dataset_id`가 이미 명시된
  경우에만 명시적 연결을 허용한다. 새 ID/manifest의 자동 생성은 아직 제공하지 않는다.

검사·통계·이전은 작업 창에서 취소할 수 있다. 취소는 현재 파일의 안전한 처리 경계에서 적용되며,
이미 끝난 원자적 활성화를 취소된 것처럼 표시하지 않는다.
