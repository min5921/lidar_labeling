# Windows 배포 계획

## 목표

대상 사용자는 Python이나 개발 도구를 설치하지 않고 Windows 10/11 x64 PC에서 앱을 실행한다. 데이터셋은 배포본에 넣지 않고 사용자가 외부 폴더를 선택한다.

## 권장 배포 전략과 현재 채택안

Qt for Python의 공식 배포 도구인 `pyside6-deploy`를 우선 사용한다. 이 도구는 Nuitka를 이용하며 Windows 실행 파일을 만들고, `standalone`과 `onefile` 모드를 지원한다.

첫 릴리스는 `standalone`으로 생성한 폴더를 ZIP으로 배포한다.

- 장점: plugin/DLL 누락을 찾기 쉽고 시작이 빠르며 현장 문제 진단이 쉽다.
- 단점: 여러 파일이 들어 있지만 사용자는 ZIP을 한 번만 풀면 된다.

기능이 안정화되면 standalone 폴더를 설치형 EXE로 감싼다. 단일 EXE(onefile)는 배포가 간단해 보이지만 매 실행 시 압축 해제, 느린 시작, 백신 오탐 가능성 때문에 1차 기본안으로 삼지 않는다.

현재 구현은 실제 PySide6/pyqtgraph/OpenGL 빌드 검증이 끝난 PyInstaller `onedir`를 채택했다.
배포 형태와 사용자 경험은 위 standalone 원칙과 같으며, `LiDARLabelTool.exe`와 `_internal/` 폴더
전체를 ZIP으로 전달한다. 패키저가 달라도 앱의 resource resolver와 사용자 파일 경로 계약은 같다.

## 생성 산출물

```text
release/
├─ LidarLabelTool-<version>-win-x64/
│  ├─ LidarLabelTool.exe
│  ├─ configs/default.json
│  ├─ schemas/*.json
│  ├─ resources/icons/*
│  ├─ qt/runtime libraries and plugins
│  ├─ LICENSES/
│  └─ README_KO.txt
├─ LidarLabelTool-<version>-win-x64.zip
└─ SHA256SUMS.txt
```

`release/`, 임시 build 폴더, compiler cache는 Git에 포함하지 않는다. 재현에 필요한 spec과 build script만 `packaging/` 및 `scripts/`에서 관리한다.

## 빌드 흐름

1. 고정된 Python과 lock file로 깨끗한 build venv를 만든다.
2. unit/integration test와 GUI smoke test를 실행한다.
3. `pyside6-deploy` standalone build를 실행한다.
4. config, schema, icon, license 누락을 검사한다.
5. 빌드 PC에서 packaged smoke test를 실행한다.
6. portable 폴더를 ZIP으로 만들고 SHA-256을 기록한다.
7. Python이 없는 clean Windows VM/PC에서 최종 검사한다.
8. 통과한 동일 산출물만 릴리스한다.

## 빌드 PC 준비사항

- 프로젝트가 지원하는 고정 Python x64 버전
- 격리된 build virtual environment
- `pyside6-deploy`가 사용하는 Nuitka 및 압축 의존성
- Windows용 compiler/SDK와 `dumpbin`을 제공하는 MSVC Build Tools
- 빌드 결과를 검사할 Windows Defender와 clean test VM 또는 별도 PC

위 항목은 빌드하는 개발 PC에만 필요하며 최종 사용자의 PC에는 Python, compiler, Qt SDK가 필요하지 않다.

## clean PC 검증표

- [ ] Python, Git, Qt SDK가 없어도 실행된다.
- [ ] 관리자 권한 없이 실행된다.
- [ ] 한글 사용자명과 공백이 포함된 경로에서 실행된다.
- [ ] 한글/공백 경로의 dataset을 연다.
- [ ] `.bin`, `.jpg/.png`, 기존 JSON을 읽는다.
- [ ] 3D/BEV/side/image view가 표시된다.
- [ ] 새 박스를 만들고 JSON을 저장·재로드한다.
- [ ] calibration 없음 상태가 정상 동작한다.
- [ ] reference-frame `MERGED`가 `Not required`로 열리고 camera calibration projection이 동작한다.
- [ ] config/schema/icon이 번들에서 로드된다.
- [ ] 로그와 사용자 설정이 쓰기 가능한 사용자 경로에 생성된다.
- [ ] 앱 종료 후 임시 파일/프로세스가 남지 않는다.
- [ ] Windows Defender/SmartScreen 동작을 기록한다.

## 지원 범위

- 1차 지원: Windows 10/11 x64
- 지원하지 않음: 32-bit Windows, ARM Windows, macOS, Linux
- GPU: 전용 GPU를 필수로 가정하지 않되 지원 OpenGL 버전은 renderer spike 후 확정
- 데이터: 외부 dataset 폴더, 네트워크 드라이브 지원은 실제 테스트 후 명시

## 릴리스 전에 결정할 것

- portable ZIP만 제공할지 설치형 EXE도 함께 제공할지
- 앱 이름, 아이콘, 제작자, 버전
- 코드 서명 여부
- 최소 Windows 및 OpenGL 버전
- 사용자 지원용 로그 내보내기 기능 포함 여부

## 실패 시 대안

`pyside6-deploy`와 선택 renderer의 결합이 안정적으로 패키징되지 않으면 PyInstaller `onedir`를 대안으로 시험한다. 패키저 교체가 앱 코드에 영향을 주지 않도록 resource resolver와 build script를 분리한다.
