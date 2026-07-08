# 데이터셋 Preflight와 라벨 QA

## 목적

라벨링을 시작하기 전에 누락된 포인트, 손상된 JSON, calibration 상태와 기존 작업 파일을
읽기 전용으로 확인한다. Preflight, stats, export는 원본 source label과 정상 working label을
수정하지 않는다.

## Preflight 실행

사람이 읽는 출력:

```powershell
lidar-label-tool preflight <dataset>
```

자동화용 JSON 출력:

```powershell
lidar-label-tool preflight <dataset> --json
```

별도 workspace를 사용한다면 다음처럼 지정한다.

```powershell
lidar-label-tool preflight <dataset> --workspace <workspace-root> --json
```

종료 코드는 다음과 같다.

- `0`: error와 warning 없음. info는 있을 수 있음
- `1`: warning만 있음
- `2`: error가 하나 이상 있음

## 검사 범위

- dataset root, adapter, frame 수, LiDAR/camera 선언
- 프레임·센서별 포인트 파일 누락/빈 파일/지원 확장자/BIN stride
- 카메라 이미지 누락과 CLI 실행 시 이미지 파일 읽기
- source LiDAR label JSON 형식, object 값, 매핑되지 않은 클래스
- reference frame, LiDAR별 calibration 상태, camera calibration 수와 fingerprint
- working label 수, 손상 파일, revision 최소/최대
- recovery snapshot 수와 손상된 recovery 파일

GUI 폴더 열기는 같은 구조 검사를 사용하지만 시작 시간을 줄이기 위해 이미지 전체 decode 검사는
생략한다. source/working JSON과 포인트 파일 메타데이터는 확인한다.

## severity 해석

- `info`: 카메라 또는 source label이 없는 것처럼 허용되는 상태
- `warning`: 일부 카메라 누락, 읽을 수 없는 이미지, Unknown class, 선택 LiDAR calibration 문제
- `error`: 포인트 파일 누락/빈 파일/stride 오류, 손상 source·working JSON, 사용 가능한 LiDAR 없음

GUI에서 error가 있어도 사용 가능한 LiDAR 프레임이 남아 있으면 경고 후 사용자가 계속할 수 있다.
사용 가능한 LiDAR 프레임이 하나도 없으면 열지 않는다.

## Calibration 상태

- `not_required`: 포인트가 이미 dataset reference frame에 있음
- `applied`: 유효한 transform으로 reference frame에 변환 가능
- `missing`: 필요한 transform 또는 calibration 파일 없음
- `invalid`: 행렬 또는 calibration JSON이 잘못됨
- `disabled`: manifest에서 센서가 명시적으로 비활성화됨

`MERGED`가 `not_required`이고 선택 raw LiDAR가 `missing`인 경우 MERGED 라벨링은 가능하다.
`missing` 또는 `invalid` raw LiDAR를 공통 좌표로 간주해 조용히 합치지 않는다.

## 라벨 통계

Source label만 집계:

```powershell
lidar-label-tool stats <dataset>
lidar-label-tool stats <dataset> --json
```

Working label만 집계:

```powershell
lidar-label-tool stats <dataset> --working
```

`--working`에서 working JSON이 없는 프레임은 객체 0개, `unvisited`로 계산한다. 현재 내부 상태의
`reviewed` 수는 JSON의 `completed_count`로도 제공한다. source label은 review 상태를 포함하지
않으므로 기본적으로 `unvisited`다.

통계에는 frame 수, 상태별 수, class별 객체 수, 프레임당 평균/최소/최대 객체 수, source/working
label 수와 recovery snapshot 수가 포함된다.

## 권장 작업 순서

라벨링 전:

1. `preflight --json`을 실행하고 종료 코드를 확인한다.
2. `invalid_bin_stride`, `missing_point_cloud`, `malformed_source_label` error를 우선 수정한다.
3. calibration 상태와 reference frame을 확인한다.
4. `stats`로 source 객체 분포를 확인한다.
5. GUI를 열고 표시된 QA 요약을 다시 확인한다.

Export 전:

1. working label을 저장한다.
2. `preflight`에서 손상된 working/recovery 파일이 없는지 확인한다.
3. `stats --working`으로 class와 frame 상태를 확인한다.
4. 명시적으로 `export`를 실행한다.

Export는 dataset/frame ID, class, 모든 box 값의 finite 여부, 양수 크기와 yaw를 출력 전에
검증한다. 다중 frame export는 모든 라벨 검증이 끝난 뒤 파일 쓰기를 시작한다.

## 알려진 제한

- PCD는 존재 여부와 빈 파일 여부를 사전 확인하지만 전체 payload 검증은 실제 로드 시 수행한다.
- GUI preflight는 시작 시간을 위해 이미지 decode 검사를 생략한다. CLI preflight는 수행한다.
- 통계는 객체 추적 연속성이나 camera별 visibility를 계산하지 않는다.
- `centerpoint_intermediate_json`은 공식 CenterPoint/OpenPCDet 학습 포맷이 아니다.
