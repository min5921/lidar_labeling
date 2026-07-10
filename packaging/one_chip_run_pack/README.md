# one_chip 실행 묶음

이 폴더는 `E:\one_chip` 원본 데이터와 `E:\one_chip_converted` 변환 결과를 다루기 위한
더블클릭용 `.bat` 모음이다. 자세한 설명은 `docs/20_ONE_CHIP_CONVERSION_MANUAL.md`를 본다.

압축 배포용 파일은 `artifacts/one_chip_run_pack.zip`으로 생성해 둘 수 있다.

원본 경로, calibration 경로, 변환/export 위치는 `.bat`를 고치지 말고
`scripts/convert_one_chip_dataset.py` 맨 위의 `User-editable defaults` 블록에서 바꾼다.
현재 one_chip 데이터의 sync 기본값은 `DEFAULT_TIMESTAMP_SOURCE = "header_aligned"`이다.
새 전체 변환의 기본 폴더 구조는 `lidar\`, `cam_left\`, `cam_right\` 단순 구조다.
예전 `sensors\lidar\MERGED\frames` 구조가 필요하면 변환 명령에 `--dataset-layout legacy`를 붙인다.

권장 순서:

```text
00_preflight_one_chip.bat
07_verify_calibration.bat
01_open_one_chip_gui.bat
```

전체 재변환이 필요할 때만 `02_convert_one_chip_full.bat`를 사용한다. 기존 output은 덮어쓰지 않는다.

포터블 앱 배포본은 `06_build_portable_app.bat`로 만든다. 결과 폴더는 `dist\LiDARLabelTool`이다.

`07_verify_calibration.bat`는 원본 calibration YAML과 변환된 `calibration.json`을 다시 비교하고,
몇 개 대표 프레임에서 LiDAR 포인트를 카메라 이미지에 투영한 overlay를
`artifacts\calibration_verify\`에 저장한다.
