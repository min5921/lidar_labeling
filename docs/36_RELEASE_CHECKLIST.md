# 릴리스 점검표와 third-party notice 수집

이 문서는 [운영 배포 계획](08_DISTRIBUTION_PLAN.md), [확정 결정](04_OPEN_DECISIONS.md),
[프로젝트 검토](35_PROJECT_REVIEW_AND_MAINTENANCE.md)의 남은 인증 항목을 추적한다.
현재 배포 방식은 `codex/v2` source와 OS별 lock 기반 `.venv`다. 실행 파일·설치 프로그램
배포, 코드 서명, 외부 공개 배포의 license 판정이 완료되었다는 뜻은 아니다.

## 1. 자동 수집 도구

저장소 루트에서 **배포에 사용할 실제 환경의 Python**으로 실행한다. 도구는 package를
import/실행하거나 설치하지 않고 `importlib.metadata`와 설치 파일 목록만 읽는다.

```powershell
# 일반 runtime dependency
.\.venv\Scripts\python.exe scripts/collect_third_party_licenses.py --output C:\release-review\runtime-notices-new

# bootstrap 및 개발/검증 도구까지 전달할 경우
.\.venv\Scripts\python.exe scripts/collect_third_party_licenses.py --include-bootstrap --include-dev --output C:\release-review\all-notices-new
```

Linux에서는 Python 경로를 `./.venv/bin/python`, 출력 경로를 아직 없는 로컬 폴더로 바꾼다.
다른 lock을 감사하려면 `--lock <path>`를 한 번 이상 지정한다. 기본은
`requirements-lock.txt`이고, 선택 옵션으로 bootstrap/development lock을 합친다.
`-r`로 포함된 같은 폴더의 lock과 현재 development lock의 `python_version` 비교 조건은
지원한다. 느슨한 버전, 임의 pip 옵션, 알 수 없는 marker, 경로 이탈, 순환 include는 거부한다.

### 산출물

| 위치 | 내용 |
|---|---|
| `manifest.json` | 고정/설치 버전, 환경, license 선언, 누락·불일치 목록, 원문 SHA-256, 수집 범위 |
| `locks/` | 사용한 lock 파일의 수정 없는 원본 byte 사본 |
| `packages/<name>/license-metadata.json` | 설치 distribution의 License/License-Expression/License-File/classifier 정보 |
| `packages/<name>/files/` | 설치 파일 목록의 license/licence/COPYING/NOTICE/COPYRIGHT와 명시 원문 |
| `README.txt` | 수집 결과의 사용 범위와 한계 |

파일 내용·줄바꿈·인코딩을 변환하지 않는다. package와 파일 목록을 정렬하고 시간·출력 절대
경로를 manifest에 넣지 않아 **같은 lock·설치 환경·파일이면 동일한 manifest byte**를 만든다.
OS/Python/설치 wheel이 다르면 원문·버전·환경 정보가 달라질 수 있으므로 각 배포 환경에서
따로 수집한다. 현재 환경의 metadata가 전 세계 모든 wheel을 대표하지는 않는다.

기존 파일·폴더는 재사용하거나 덮어쓰지 않는다. 원본 데이터·작업 라벨이 아닌 **새 출력
폴더**를 선택한다. 쓰기 실패 시 새로 만든 일부 산출물이 남을 수 있으며 이를 자동 삭제하지
않는다. 완성 manifest가 원자적으로 공개되어야 수집 완료이며, 읽을 수 없는/불완전한
manifest는 완료로 보지 않는다. 내용을 확인한 후 다른 새 경로로 재시도한다. 완료 marker
공개에는 hard link를 지원하는 로컬 파일시스템이 필요하다.

### 종료 코드와 읽는 순서

- `0`: 자동 검사에서 누락/불일치 경고를 찾지 못함. 법적 검토 완료를 뜻하지 않는다.
- `1`: 수집은 완료했지만 license 대안/참조, 원문 부족 등 확인할 경고가 있음.
- `2`: package 누락·버전 불일치·원문 읽기 실패 또는 수집 자체 실패. manifest가 있으면
  `error_count`와 `issues`를 먼저 확인한다.

`manifest.json`의 `legal_review_required`는 항상 `true`다. `issues`의 package/code를 확인하고
누락 원문·선택 조건을 검토한다. 파일 수만 보고 모든 원문이 포함되었다고 판단하지 않는다.
하위 native component의 notice만 있고 package 자체 원문이 보이지 않는 경우도 구분한다.

## 2. 현재 수집 검증 기록

2026-09-13 기존 Windows Python 3.12 환경에서 runtime + bootstrap + development lock을
대상으로 수집을 실행했다. **29 distributions, notice 원문 108개, error 0, warning 7**이었다.
이는 해당 설치 환경의 수집 결과이며 새 clean 환경 인증이나 법적 검토 결과가 아니다.

- NumPy·packaging·PySide6 계열의 대안/참조 선언은 적용 조건 검토 대상으로 남았다.
- PyOpenGL은 포함된 native 구성요소의 notice 3개를 수집했지만 package 자체 원문 확인은
  별도로 필요하다.
- 현재 PySide6/PySide6_Addons/PySide6_Essentials/shiboken6 wheel의 등록된 원문은
  `LicenseRef-Qt-Commercial.txt`였다. 이 파일이 있다는 사실만으로 상업용 license 보유나
  오픈소스 조건 이행을 추정하면 안 된다.
- Python 인터프리터, OS/GPU/Visual C++ runtime, 등록되지 않은 bundled native component는
  이 distribution 수집만으로 점검되지 않는다.
- 기존 [Third-Party 요약](../THIRD_PARTY_NOTICES.md)은 전체 원문 묶음을 대체하지 않는다.

수집 자료는 Git 제외 `artifacts/third-party-licenses/`에 보관했다. 갱신된 lock 또는 다른 OS를
배포할 때는 다시 실행하고 해당 release와 함께 보관·전달할 notice 범위를 확인한다.

## 3. 실제 운영 인증

다음 항목은 증거가 있을 때만 완료로 표시한다. 합성/offscreen 회귀가 실제 장비 검증을
대체하지 않는다. 결과 기록에는 commit, OS/build, Python, GPU/driver, dataset/profile,
수행 날짜와 관찰 결과를 남긴다.

- [x] 기능 commit `2b0365c`의 GitHub Windows/Ubuntu × Python 3.10/3.12
  [네 job 통과](https://github.com/min5921/lidar_labeling/actions/runs/34730643435).
  로컬 새 한글·공백 경로 venv 486 passed, 2 skipped; 실제 Windows/OpenGL interaction smoke OK.
  CI skip 이유와 실제 표본 QA 한계는 [검증 기록](35_PROJECT_REVIEW_AND_MAINTENANCE.md#후속-검증-환경)을 따른다.
- [ ] 새 Windows PC에서 공식 Python x64 → setup → Qt DLL 검사 → 실제 OpenGL 표시
- [ ] 대상 Linux desktop에서 설치·GUI 표시와 GPU 상호작용 확인
- [ ] 한글·공백 경로의 BIN/PCD+이미지 폴더 구성, profile 선택, 열기
- [ ] 카메라/보정 누락, 손상 BIN/JSON, 읽기 전용 원본과 외부 workspace 확인
- [ ] 객체 ID·class·box·unknown metadata 저장 후 재로드, Undo 후 재저장 확인
- [ ] 비정상 종료 recovery와 외부 라벨 변경 충돌의 사용자 안내 확인
- [ ] 네트워크 공유의 실제 동시 쓰기/lock 실패·복구 확인
- [ ] 차량·사람·공중 표지판에서 선택 객체 추적과 지면 z ON/OFF 확인
- [ ] 가림·유사 객체·포인트 부족 시 잘못 이동하지 않는 fallback 확인

## 4. 버전·아이콘·권리·서명

아래 결정이 필요하다고 해서 로컬 source 운영에 실행 파일 패키징을 추가하지 않는다.
현재 정책은 [확정 결정 D39](04_OPEN_DECISIONS.md)에 따른다.

| 항목 | 현재 확인 가능한 사실 | 남은 조치 |
|---|---|---|
| 버전 | `pyproject.toml`과 `src/lidar_label_tool/__init__.py`가 version을 선언 | release마다 두 값·tag·문서·commit 일치 검사 |
| 앱 표시 이름 | `LiDAR Label Tool` 사용 | 배포 소유자가 최종 표기 확정 |
| 전용 아이콘 | `resources/icons/`에는 placeholder만 존재 | 소유권이 확인된 icon 선택/제작 및 적용은 별도 결정 |
| 프로젝트 자체 license | 저장소에 별도 프로젝트 `LICENSE` 미선언 | 배포 소유자가 권리와 외부 전달 조건을 정하고 문서화 |
| third-party 원문 | 수집 도구와 manifest 제공 | package/native 구성요소별 실제 필요 자료 확인, 해당 release에 묶기 |
| 제작자/회사/저작권 | 확정 결정 문서에 미확정으로 남음 | 소유자 확인 후 실제 정보 반영 |
| 코드 서명 | 현재 source 운영, 서명된 설치 파일 배포 아님 | 실행 파일 배포를 다시 정할 때 인증서·서명 주체·검증 절차 결정 |

이 점검표와 자동 수집기는 법적 판단, 재배포 허가, 보안 감사 또는 코드 서명 증명서가 아니다.
확인이 필요한 조건을 감추지 않고 release 담당자가 근거를 남기도록 돕는 도구다.
