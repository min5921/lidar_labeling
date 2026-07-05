# Local sample data

사용자가 전달하는 원본 데이터는 다음처럼 넣는다.

```text
local_data/
└─ incoming/
   └─ <dataset_name>/
      └─ 원본 파일과 폴더 구조 그대로
```

파일명, 센서명, 폴더 구조를 미리 바꾸지 않는다. 원본 구조를 먼저 검사한 뒤 dataset adapter와 정규화 계약을 확정한다.

`incoming/`의 실제 데이터는 Git에 포함되지 않는다.

