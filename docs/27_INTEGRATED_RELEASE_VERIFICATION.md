# 통합 EXE v0.2.0 r2 검수 기록

검수일: 2026-07-12

브랜치: `codex/integrated-desktop-workflows`

## 1. 산출물

```text
release_packages/LiDARLabelTool_Integrated_0.2.0_r2.exe
release_packages/LiDARLabelTool_Integrated_0.2.0_r2.sha256.txt
```

- EXE size: `82339147` bytes
- SHA-256: `C9A6D1D3803BCDC3F08E99E5756D6AEAF4C120BDAD81FFA358BB18E1C8FF498B`
- File version: `0.2.0`
- Product version: `0.2.0`
- Product name: `LiDAR Label Tool`
- 디지털 서명: 없음

## 2. 통합 기능

- 데이터셋 열기
- one_chip 원본 MCAP/YAML 전체 변환
- 기존 dataset의 timestamp 재동기화
- Calibration JSON 생성
- Calibration YAML/JSON 대조와 대표 frame projection overlay 검증
- dataset Preflight
- source/working label 통계
- 명시적 label export
- `%LOCALAPPDATA%\LiDARLabelTool\settings.ini` 최근 경로 저장
- 변환 진행 log와 취소 요청
- 전체 변환 staging 정리와 기존 output 비덮어쓰기
- 재동기화 `frames.jsonl` 백업과 원자적 교체

GUI와 CLI는 패키지 service를 함께 사용하며 EXE는 PowerShell 또는 BAT를 실행하지 않는다.

## 3. 코드 검증

- `pytest`: `115 passed`
- `ruff check .`: 통과
- `git diff --check`: 통과
- workflow Qt 단위 테스트: 통과
- 기존 one_chip 변환/Calibration/동기화 회귀 테스트: 통과
- CLI export 공용 서비스 회귀 테스트: 통과

pytest는 기능과 무관한 `.pytest_cache` 쓰기 권한 경고 1건을 출력했다.

## 4. UI와 실행 검증

- 통합 시작 화면 580 x 380 offscreen 렌더: 겹침·잘림 없음
- 변환 화면 760 x 610 offscreen 렌더: 겹침·잘림 없음
- one-file EXE Windows GUI smoke: 12초 이상 실행 유지
- one-file 부트로더/앱 프로세스: 2개 확인
- smoke 종료 후 잔여 프로세스: 0
- smoke 중 crash log 변화: 없음

offscreen Qt 렌더에서는 한글 글리프가 사각형으로 표시되었으므로 실제 Windows 화면의 한글 표시는
clean-PC 현장 검수에서 다시 확인한다.

## 5. 빌드 경고

PyInstaller 빌드는 성공했으나 다음 선택 모듈 경고가 있었다.

- `pyqtgraph.jupyter`: `jupyter_rfb` 없음
- `OpenGL.raw.GLES3`: 데스크톱 Win32에서 GLES2 attribute 없음
- PyOpenGL의 오래된 선택 GLUT/GLE DLL: `MSVCR90.dll` 없음

현재 앱은 Qt 데스크톱 OpenGL을 사용한다. clean-PC에서 3D view를 실제로 확인하기 전까지 경고를
무시한 것으로 처리하지 않는다.

## 6. 남은 필수 Gate

- `E:\one_chip`, `E:\one_chip_converted`가 현재 세션에 없어 r2 실데이터 전체 변환/재동기화 미검증
- 실제 one_chip Calibration projection overlay r2 재검증 필요
- Python 미설치 Windows 10/11 x64 clean PC 검증 필요
- 한글·공백 경로의 source/output 변환과 open/edit/save/reload 검증 필요
- Windows Defender/SmartScreen 결과 기록 필요
- 코드 서명 필요
- 프로젝트 자체 라이선스 결정 필요
- 전용 애플리케이션 아이콘 필요. 현재 EXE는 PyInstaller 기본 아이콘 사용
- 압축 MCAP chunk 지원 필요. 현재는 명시적 오류로 중단

## 7. 알려진 데이터 검수 불일치

현재 로컬 `merged_device_full` 샘플은 manifest에 `SIDE_RIGHT`를 선언했지만 모든 198 frame의 이미지가
없어 Preflight가 `errors=0, warnings=198`을 반환한다. 기존 r6 문서의 `warnings=0` 기록과 다르다.

이 샘플을 다음 릴리스 Gate에 사용할 때는 아래 중 하나를 먼저 결정한다.

- 실제로 없는 `SIDE_RIGHT` 선언을 manifest에서 제거
- 누락 camera가 의도된 fixture임을 문서화하고 expected warning으로 관리

사용자 데이터이므로 검수 과정에서 manifest를 임의로 수정하지 않았다.
