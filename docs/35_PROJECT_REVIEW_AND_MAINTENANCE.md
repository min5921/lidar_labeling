# 프로젝트 검토·유지보수

검토일: 2026-09-13. 기준 브랜치 `codex/v2`, 시작 commit `ee7e94f`.
사용자가 전체 정리·검토 및 발견 오류의 수정·회귀 테스트를 승인한 범위다.
현재 규범은 [확정 결정](04_OPEN_DECISIONS.md), [v2 계약](32_GENERIC_DATASET_V2_CONTRACT.md),
[위험 Gate](13_PRE_IMPLEMENTATION_AUDIT.md)를 따른다.

## 결론

v2 입력 구성→profile 편집→저장 흐름은 유지하고, 실제 재현된 데이터 보호·UI 상태·운영 검증
누락을 보강했다. 전체 테스트가 통과하더라도 모든 오류가 없다는 뜻은 아니다. 실제 GPU와
센서 데이터 추적 정확도, clean Windows/Linux 설치 인증은 별도 Gate다.

### 재현 후 수정한 항목

| 우선순위 | 재현한 문제 | 수정 및 회귀 범위 |
|---|---|---|
| P1 | 열린 working JSON을 외부에서 같은 revision으로 바꾸면 저장 시 무경고 덮어씀 | v1/v2 load byte hash baseline, 반복 저장 거부, 재로드 후 정상 저장, 백업 복사 중 변경 검사 |
| P1 | 저장 후 Undo가 예전 revision을 되살려 다음 저장이 충돌함 | undo/redo의 저장 context만 최신 baseline으로 갱신, 편집 이력·unknown metadata 유지 |
| P1 | export 출력으로 작업 라벨 폴더를 지정하면 형식이 다른 JSON으로 대체됨 | 기존 파일·동시 생성 출력 비덮어쓰기, 보호 namespace 안 신규 export 생성도 거부 |
| P1 | 여러 LiDAR 중 기본 profile만 GUI export/통계/검사에 사용됨 | 작업 직전 명시적 profile 선택과 취소, worker에 선택값 snapshot 전달 |
| P1 | setup의 임의 `-EnvironmentDirectory`가 `-Recreate` 삭제 대상으로 허용됨 | 정확한 프로젝트 `.venv`만 허용, reparse point 및 `pyvenv.cfg` 없는 폴더 보존 |
| P1 | 이전 frame의 BEV/측면 드래그를 놓으면 다음 frame 동일 ID 박스가 변경됨 | frame 요청/박스 교체 시 gesture 취소, 로드 중 새 편집 차단 |
| P1 | Ctrl+3D 휠/드래그 후 Ctrl을 놓으면 박스 z도 내려감 | 포인터 제스처와 Ctrl 단독 키 동작 분리 |
| P2 | 카메라 profile 뒤 lidar-only profile이 있으면 재동기화 실패 | method별 카메라 후보 격리, profile 순서 양쪽·라벨/원본 비변경 검사 |
| P2 | calibration 변경 뒤 옛 투영은 남고 저장 상태만 새 hash로 갱신됨 | runtime 변경 경고와 투영 캐시 해제, semantic-invalid/disabled 상태 검증; LiDAR 편집 유지 |
| P2 | 운영 `codex/v2` push에 CI가 실행되지 않고 Python 3.12 검사 없음 | 운영 브랜치 trigger와 두 OS × 두 Python matrix, Ruff/pytest/mypy와 dev lock |

P1/P2는 이번 코드 검토의 수정 우선순위다. 과거 설계 문서의 P0 Gate 분류와 혼동하지 않는다.
삭제·덮어쓰기 재현은 임시 합성 데이터나 mock에서만 수행했으며 사용자 데이터로 실행하지 않았다.

## 폴더 역할 정리

| 위치 | 역할 | 정리 정책 |
|---|---|---|
| `launchers/windows`, `launchers/linux` | 사용자가 설치·실행하는 진입점 | 일반 사용자는 이 경로 사용 |
| `src/lidar_label_tool` | domain/geometry/I/O/service/worker/UI | [현행 아키텍처](02_ARCHITECTURE.md) 기준으로 책임 구분 |
| `schemas`, `configs` | 계약과 읽기 전용 기본 설정 | source와 함께 버전 관리 |
| `scripts` | 개발 검사와 포맷별 변환 보조 | [도구 안내](../scripts/README.md), 공통 로직은 service로 분리 |
| `packaging`, `launchers/legacy` | 특정 one_chip/Waymo 샘플 보조 | 일반 v2 경로와 분리, 의존성 확인 없이 삭제 금지 |
| `tests` | 단위·통합·schema/GUI 회귀 | 새 오류는 최소 재현을 테스트로 유지 |
| `docs` | 현행 계약·설치·사용법과 설계 이력 | 현행 우선순위 명시, 기존 링크 유지 |
| `local_data`, 외부 데이터·라벨 workspace | 사용자 데이터 | 코드 정리 대상에서 제외 |
| `.venv`, cache, `artifacts`, `outputs`, `dist`, `release_packages` | 로컬 환경/검증/산출물 | Git 제외, 필요 여부 확인 없이 삭제하지 않음 |

중복된 빈 폴더 표식 `scripts/.gitkeep`, `src/lidar_label_tool/calibration/.gitkeep` 두 개만
제거했다. 이미 파일이 있는 폴더라 표식이 필요 없고 Git에서 복원 가능하다. 빈 icon/fixture
폴더의 표식은 유지했다. 역사 문서나 원본/작업 라벨, 이전 배포 산출물은 이동·삭제하지 않았다.

`docs/README.md`와 AEVA MCAP 변환 문서·스크립트·테스트는 검토 시작 전부터 있던 별도 미커밋
작업이다. 해당 네 파일은 이번 정리에서 수정하지 않았다. 기존 코드에 문제가 있다는 이유로
작업 이력을 삭제하거나 전부 새로 쓰지 않았다.

## 검증

최종 코드 동결 후의 로컬 실행 결과다. 검증 명령은 [scripts 안내](../scripts/README.md)를 따른다.

- Windows, 기존 공식 Python 3.12.14 가상환경; PySide6/Qt 6.11.1 환경 검사 통과.
- 전체 로컬 pytest: **365 passed, 2 skipped, 6 subtests passed**.
- 별도 MCAP 미커밋 테스트 제외: **351 passed, 2 skipped, 6 subtests passed**.
- 두 skip은 Windows 심볼릭 링크 생성 권한이 필요한 export 경로 우회 테스트다. 해당 실파일
  시나리오의 통과를 주장하지 않으며 Linux/권한이 허용된 환경에서 추가 확인한다.
- 저장소 전체 Ruff, 전체 `src` 99개 파일 mypy, `pip check`, `git diff --check` 통과.
- Markdown 35개 문서의 로컬 파일 링크 누락 0개(heading anchor는 별도), Git에 추적된 주요
  가상환경/cache/검증/배포 생성물 0개. 빈 폴더 표식 제거 이외의 사용자 파일 삭제 없음.
- 이번 작업에서 새 clean 환경 설치, Linux 실제 실행, GitHub runner 실행은 하지 않았다.
- 기존 실제 OpenGL smoke 기록은 과거 검증이며 이번 offscreen 회귀와 구분한다.

## 변경된 사용 조건

- 외부에서 작업 JSON을 바꿨다면 저장을 반복하지 말고 변경 내용을 확인한 뒤 재로드한다.
  다른 repository 인스턴스에 기존 라벨을 넘겨 저장할 때도 먼저 해당 repository로 load해야 한다.
- export는 새 경로를 사용한다. 완성 파일의 원자 공개에는 hard link가 필요하며 미지원
  파일시스템은 덮어쓰기 방식으로 우회하지 않고 실패한다. 로컬 NTFS/ext4에 출력 후 복사한다.
- 세션 중 보정 파일을 바꾸면 기존 투영을 끄고 다시 열기를 안내한다. 화면 조작/프레임 로드/
  저장 시 검사하며 실시간 파일 감시 서비스는 아니다. LiDAR 박스와 저장은 계속 사용할 수 있다.
- 설치 복구 시 `.venv/pyvenv.cfg`가 없으면 자동 삭제하지 않는다. 기존 폴더를 검토·보존한 뒤
  새 환경을 만든다.

## 다음 정리 순서와 남은 Gate

1. **운영 인증:** GitHub 네 matrix job 통과를 확인하고 새 Windows PC에서 한글·공백 경로,
   OpenGL 표시, 저장·재로드·복구를 검수한다. 네트워크 공유 폴더의 실제 동시 쓰기·lock도 별도 검증한다.
2. **실제 데이터 QA:** 차량·사람·공중 표지판, 가림/포인트 부족/유사 객체에서 추적 성공과 보수적
   fallback을 확인한다. 지면 z 옵션은 객체별 기본 OFF이며 크기/yaw는 추적하지 않는다.
3. **작은 단위 구조 개선:** `MainWindow`의 frame 전환, 편집 명령, 추적 상태, 뷰 갱신 책임을
   기존 회귀 테스트를 유지하며 단계적으로 분리한다. 검사·통계·export의 공용 busy worker에도
   취소 token/진행률을 확대한다. 이번에는 대규모 파일 이동/재작성을 하지 않았다.
4. **보류 기능:** reviewed/skipped 작업 흐름, source-compatible exporter, 전체-frame v1→v2
   migrator는 별도 구현 범위다. 부분 객체 가져오기나 일반 GUI export와 혼동하지 않는다.
5. **문서/릴리스:** 실제 인증 결과를 기록한 뒤 역사 문서 archive, 라이선스 묶음·버전/아이콘·서명
   범위를 결정한다. 링크·외부 사용 여부 확인 없이 레거시 경로를 삭제하지 않는다.
