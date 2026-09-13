# 개발·검증 도구

일반 설치·실행은 [launchers](../launchers/README.md)를 사용한다. 이 폴더는 프로그램 내부
진입점이 아니라 개발·검증 및 특정 원본 포맷의 변환 보조 도구를 관리한다.

| 파일 | 용도 | 범위 |
|---|---|---|
| `setup_windows.ps1` | Windows launcher가 호출하는 설치·복구 구현 | 운영 설치 |
| `verify_source_environment.py` | Python/lock/package/Qt native DLL 검사 | 운영·개발 공통 |
| `validate_tracking_sample.py` | 실제 인접 frame의 동일 source ID로 추적 보조 표본 검사 | 읽기 전용 QA |
| `collect_third_party_licenses.py` | lock 기준 설치 metadata·license 원문·SHA 수집 | 배포 준비, 법적 적합성 판정 아님 |
| `gui_smoke.py`, `interaction_smoke.py` | 실제 화면과 상호작용 smoke 검증 | 개발·실험실 검증 |
| `convert_one_chip_dataset.py` | 특정 one_chip bag/calibration 변환 | 레거시 전용 |
| `verify_one_chip_calibration.py` | one_chip 보정 검증 | 레거시 전용 |
| `convert_waymo_to_merged_device.py` | Waymo 자료의 명시적 MERGED 전처리 | 레거시 전용 |
| `check_waymo_projection.py` | Waymo camera projection 검증 | 레거시 전용 |

범용 BIN/PCD+이미지 폴더 구성과 timestamp 재동기화는 GUI 및 `services/`의 v2 경로를 사용한다.
새 기능은 service/loader/exporter에 구현하고 이 폴더에 동일 로직을 복제하지 않는다.

## 저장소 루트에서 검증

Windows 개발 환경은 [소스 설치 안내](../docs/31_LAB_SOURCE_SETUP.md)의 development lock 설치를
먼저 따른다. 다음 명령은 데이터셋·작업 라벨을 정리하거나 삭제하지 않는다.

```powershell
.\.venv\Scripts\python.exe scripts/verify_source_environment.py
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -m pytest -q
```

Linux에서는 Python 경로를 `./.venv/bin/python`으로 바꾸고
`QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m pytest -q`를 사용한다.
Offscreen 테스트는 실제 GPU/OpenGL·마우스 조작 인증을 대체하지 않는다.

추적 표본 검사는 `--max-frames 4 --max-objects-per-pair 12`로 범위를 제한할 수 있다.
Source 중심과의 오차는 참고값이며 자동 추적의 일반 정확도나 표지판 성공을 보장하지 않는다.
라이선스 수집 옵션과 미완료 권리 검토는 [릴리스 체크리스트](../docs/36_RELEASE_CHECKLIST.md)를 따른다.

## 정리 원칙

- `.venv`, cache, `artifacts/`, `outputs/`, `dist/`, `release_packages/`는 Git 제외 산출물이다.
- Git 제외라는 이유만으로 삭제하지 않는다. 이미지·검증 기록·릴리스 산출물이 들어 있을 수 있다.
- `local_data/`, 원본·라벨·recovery·generation은 일반 코드 정리 대상이 아니다.
- 변환 스크립트는 신규/레거시 여부와 입력 계약을 문서화한 후 추가한다. 미커밋 작업을 임의로
  합치거나 삭제하지 않는다.
