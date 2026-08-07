# 문서 안내

문서 수가 많아도 모두 같은 우선순위는 아니다. 새 범용 데이터셋 작업은 아래 순서로 읽는다.

## 범용 데이터셋 v2: 먼저 읽기

1. [`32_GENERIC_DATASET_V2_CONTRACT.md`](32_GENERIC_DATASET_V2_CONTRACT.md):
   활성 LiDAR 1개, 카메라 0~1개, timestamp, profile, 라벨 identity의 최종 계약
2. [`33_GENERIC_DATASET_SETUP_GUIDE.md`](33_GENERIC_DATASET_SETUP_GUIDE.md):
   원본 폴더 자동 탐색, 프로그램 내 구성, 기존 v2 LiDAR profile 추가와 재동기화 사용법
3. [`04_OPEN_DECISIONS.md`](04_OPEN_DECISIONS.md): 확정 결정과 아직 보류된 범위
4. [`03_DATA_CONTRACTS.md`](03_DATA_CONTRACTS.md): 기존 v1과 v2 데이터 구조의 경계
5. [`18_PREFLIGHT_AND_QA.md`](18_PREFLIGHT_AND_QA.md): 열기 전 검사와 오류 등급

v2 스키마 원본은 저장소의 `schemas/`에 있다. 현재 GUI는 `dataset.json`이 없는 폴더를 구성
화면으로 연결하고, profile별 v2 라벨 저장과 분석 후 원자적 재동기화를 지원한다.

## 현재 프로그램 사용

- [`../README.md`](../README.md): 설치, 실행, 현재 제공 기능
- [`USER_MANUAL.md`](USER_MANUAL.md): GUI 라벨링 사용법
- [`19_TRIAL_RUN_MANUAL.md`](19_TRIAL_RUN_MANUAL.md): 실제 데이터 검수 절차
- [`31_LAB_SOURCE_SETUP.md`](31_LAB_SOURCE_SETUP.md): Windows/Linux 개발 환경

## 설계와 구현 관리

- `01_PRODUCT_SPEC.md`, `02_ARCHITECTURE.md`, `05_IMPLEMENTATION_PLAN.md`
- `06_INTERACTION_SPEC.md`, `14_UX_SAFETY_SPEC.md`
- `15_IMPLEMENTATION_STATUS.md`, `25_INTEGRATED_DESKTOP_WORKFLOWS.md`

## 기존·특수 입력 호환

- [`11_DEVICE_CENTRIC_INPUT.md`](11_DEVICE_CENTRIC_INPUT.md): 기존 device-centric v1 입력
- [`09_CALIBRATION_PLAN.md`](09_CALIBRATION_PLAN.md): 기존 calibration 흐름
- [`20_ONE_CHIP_CONVERSION_MANUAL.md`](20_ONE_CHIP_CONVERSION_MANUAL.md):
  특정 `calibration + rosbags` 자료용 one_chip 변환기
- [`12_EXISTING_LABEL_WORKFLOW.md`](12_EXISTING_LABEL_WORKFLOW.md): 기존 source label 호환

이 기능들은 현재 사용자를 위해 보존한다. 범용 v2의 기본 입력 방식으로 간주하지 않는다.

## 감사·이력 자료

`07_PROJECT_REVIEW.md`, `10_SAMPLE_DATA_AUDIT.md`, `13_PRE_IMPLEMENTATION_AUDIT.md`,
`16_IMPLEMENTATION_REVIEW.md`, `21_COMMIT_UPDATE_LOG.md`는 당시 상태를 기록한 참고 자료다.
현재 계약과 충돌하면 `32_GENERIC_DATASET_V2_CONTRACT.md`와 `04_OPEN_DECISIONS.md`를 우선한다.

파일을 즉시 삭제하거나 이동하면 기존 링크와 검수 근거가 끊길 수 있어, 이 단계에서는 역할별로
분류만 했다. v2 GUI와 migration이 완료된 뒤 사용되지 않는 이력 문서를 별도 archive로 옮긴다.
