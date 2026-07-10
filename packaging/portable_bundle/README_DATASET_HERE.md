# 데이터셋 위치

변환 완료 데이터셋 폴더를 이 폴더 아래에 둘 수 있다.

```text
datasets/
└─ one_chip_converted/
   ├─ dataset.json
   ├─ lidar/ 또는 sensors/
   ├─ cam_left/ 또는 sensors/camera/
   ├─ sync/frames.jsonl
   └─ calibration/calibration.json
```

데이터셋이 정확히 하나이면 상위 폴더의 `Start_LiDAR_Label_Tool.bat`이 자동으로 연다.
데이터셋은 앱과 별도 드라이브에 두어도 되며, 폴더를 실행 배치 위로 드래그하거나 앱에서 직접
선택하면 된다.
