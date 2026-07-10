# LiDAR Label Tool 포터블 배포본

배포 이름: `{{RELEASE_NAME}}`

## 실행

`LiDARLabelTool.exe`를 더블클릭하고 `dataset.json`이 있는 데이터셋 폴더를 선택한다.
데이터셋 폴더를 `Start_LiDAR_Label_Tool.bat` 위로 드래그해도 바로 열 수 있다.

기본 데이터셋 경로는 `Open_Configured_Dataset.bat`의 `DATASET` 한 줄에서 바꿀 수 있다.
패키징 시 설정된 값은 `{{DEFAULT_DATASET_PATH}}`이다.

`datasets` 아래에 데이터셋 폴더가 정확히 하나 있으면 `Start_LiDAR_Label_Tool.bat`이 자동으로
그 데이터셋을 연다.

## 주의

- `LiDARLabelTool.exe`와 `_internal` 폴더는 항상 함께 둔다.
- Python, ROS2, MCAP 패키지는 라벨링 PC에 설치하지 않아도 된다.
- 원본 MCAP/YAML은 이 앱이 직접 열지 않는다. 변환 완료 데이터셋을 사용한다.
- crash log는 `%LOCALAPPDATA%\LiDARLabelTool\logs\LiDARLabelTool_crash.log`에 기록된다.

상세 절차와 검수 항목은 `manuals` 폴더를 참고한다.
