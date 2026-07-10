# 요구사항 재검수 결과

검수일: 2026-07-10

브랜치: `codex/portable-distribution`

최종 로컬 검수본: `LiDARLabelTool_Portable_20260710_r6`

## 결론

one_chip 변환, simple device-centric 입력, 안전 저장, source/calibration 변경 감지, frozen resource,
portable 실행과 재현 가능한 패키징까지 코드·로컬 검수 기준을 통과했다. 별도 Python 미설치 PC와
한글/공백 경로의 최종 현장 검증은 아직 필요하다. 현재 세션에는 `E:` 드라이브가 연결되지 않아
r6로 `E:\one_chip_converted`를 다시 검사하지 못했으며, 이전 r4 검수 결과를 이월 기록했다.

## 이번에 수정한 문제

1. simple manifest의 `storage_layout`이 `dataset.schema.json`에서 거부되던 오류
2. frozen 앱이 `_internal/configs/default.json` 대신 현재 작업 폴더 config로 fallback할 위험
3. 읽기 전용 배포 폴더에서 EXE 옆 crash log 쓰기가 실패할 위험
4. 최종 release 폴더와 ZIP을 수작업으로 조립해 재현할 수 없던 문제
5. source label과 calibration 변경을 working label load/save에서 알리지 않던 문제
6. working JSON의 알 수 없는 frame/object field가 round-trip에서 사라지던 문제
7. 사용자 매뉴얼의 “portable 제작 전” 및 legacy 폴더 예시 등 문서 드리프트

## 개발 원칙 20개 대조

| 번호 | 상태 | 확인 결과 |
|---:|---|---|
| 1 | 통과 | 계약·위험 Gate·보류 범위를 먼저 재검토함 |
| 2 | 통과 | x/y/z, meter, radian yaw, `T_target_source` 의미 유지 |
| 3 | 통과 | UI는 adapter/service 결과를 사용하고 dataset JSON을 직접 파싱하지 않음 |
| 4 | 통과 | domain은 Qt/OpenGL/OpenCV에 의존하지 않음 |
| 5 | 통과 | device/frame 입력은 adapter와 point loader 경계로 분리 |
| 6 | 통과 | 저장과 exporter registry를 분리 |
| 7 | 통과 | working label은 revision 비교, 임시 검증, `os.replace`, `.bak` 사용 |
| 8 | 통과 | 원본 `PointCloudData`와 렌더 캐시/downsample을 분리 |
| 9 | 통과 | reference-frame MERGED는 calibration 없이 사용, 잘못된 sensor-local cloud는 제외 |
| 10 | 통과 | 변경 회귀 테스트 포함, 총 111 tests 통과 |
| 11 | 부분 | one-folder EXE 로컬 실행 통과, Python 미설치 별도 PC 인증은 미완료 |
| 12 | 통과 | 번들 config는 `_MEIPASS`, crash log는 `%LOCALAPPDATA%` 사용 |
| 13 | 통과 | Missing/Invalid/Disabled sensor-local LiDAR를 공통 좌표로 합치지 않음 |
| 14 | 통과 | calibration JSON과 내부 설명에서 `T_target_source` 방향 유지 |
| 15 | 통과 | source label은 읽기 전용, working save와 export 분리 |
| 16 | 통과 | source ID/raw metadata 및 unknown working frame/object field 보존 |
| 17 | 통과 | frame load request generation으로 오래된 결과 폐기 |
| 18 | 통과 | worker는 순수 데이터만 처리하고 Qt/GL 갱신은 main thread signal에서 수행 |
| 19 | 통과 | working revision/hash와 source fingerprint를 저장 직전 다시 비교 |
| 20 | 통과 | calibration fingerprint 변경을 preflight와 GUI에서 경고하고 저장 전 재확인 |

## 완료 Gate

| Gate | 상태 | 근거 또는 남은 작업 |
|---|---|---|
| tests | 통과 | source venv와 build venv 모두 `111 passed` |
| lint | 통과 | 두 venv 모두 `ruff check .` 통과 |
| manifest/schema | 통과 | simple/legacy converter manifest 실제 검증 통과 |
| 로컬 preflight | 통과 | 198-frame Waymo dataset errors 0, warnings 0 |
| r6 EXE | 통과 | 12초 실행, 정상 창 닫기, exit 0, crash log/lock 잔여 없음 |
| r6 launcher | 통과 | `Start_LiDAR_Label_Tool.bat <dataset>` 실행과 lock 정리 확인 |
| one_chip r6 실데이터 | 보류 | 현재 세션에 `E:` 드라이브가 없음 |
| one_chip 이전 검수 | 통과 | r4에서 3754 frames, preflight/calibration errors 0, warnings 0 |
| clean Windows | 보류 | Python 미설치 PC, 한글/공백 경로 open/edit/save 필요 |
| calibration 추적 | 부분 | UI 상태 badge와 JSON fingerprint는 있음. 사용 행렬의 일반 session log는 후속 |
| 정적 타입 검사 | 부분 | release gate는 ruff. mypy는 pyqtgraph event typing 등 기존 오류가 남음 |

## 최종 산출물

```text
release_packages/LiDARLabelTool_Portable_20260710_r6/
release_packages/LiDARLabelTool_Portable_20260710_r6.zip
release_packages/LiDARLabelTool_Portable_20260710_r6.sha256.txt
```

ZIP size: `82994162` bytes

SHA-256: `55477CBF38BC9E3E7B6C57EAE65BF33945213C695DA50DDC86543DFB608336B3`

## 배포 전 마지막 현장 절차

1. r6 ZIP을 Python이 없는 Windows 10/11 x64 PC에 복사한다.
2. `D:\라벨링 테스트\LiDAR Label Tool\`처럼 한글과 공백이 있는 경로에 압축 해제한다.
3. 변환 데이터셋도 한글/공백 경로에 복사한다.
4. EXE 실행, point/camera/frame 이동, 박스 생성·편집·저장·재실행을 확인한다.
5. 강제 종료 recovery와 두 앱 session lock을 확인한다.
6. SmartScreen/백신/OpenGL 결과를 `docs/22_PORTABLE_DISTRIBUTION_CHECKLIST.md`에 기록한다.
