## 배포 파일

- `LiDARLabelTool_Integrated_0.2.1_windows_x86_64.exe`
- `LiDARLabelTool_Integrated_0.2.1_windows_x86_64.sha256.txt`
- `LiDARLabelTool_Integrated_0.2.1_linux_x86_64.tar.gz`
- `LiDARLabelTool_Integrated_0.2.1_linux_x86_64.tar.gz.sha256.txt`

Windows 10/11 x64와 Ubuntu 22.04 이상 x86_64를 지원한다. 두 배포본 모두 Python, pip, ROS2를
별도로 설치하지 않고 통합 GUI에서 데이터 변환, 재동기화, calibration 생성·검증, preflight,
데이터셋 열기와 라벨 편집을 실행할 수 있다.

## 주요 변경

- MCAP/YAML one_chip 원본 데이터의 device-centric dataset 변환 통합
- header timestamp 기반 nearest sync와 반복·점프 QA
- LiDAR 기준 camera calibration 변환 및 projection overlay 검증
- Windows/Linux 공용 통합 작업 선택 화면
- Linux XDG 설정·로그·데이터 경로 지원
- Windows와 Ubuntu 네이티브 CI 빌드, smoke test, SHA-256 검증

## 검증 상태

- Windows 개발 PC: 전체 테스트 121개 통과, Ruff 통과, packaged offscreen smoke 통과
- Ubuntu 22.04 CI: 테스트 114개 통과, sample 부재 integration 7개 skip, Ruff 통과
- Ubuntu offscreen 및 Xvfb/xcb packaged smoke 통과
- Windows/Linux release SHA-256은 각 자산 옆의 검증 파일로 제공

실제 운영 PC에서는 한글·공백 경로, one_chip 전체 변환, camera frame 진행, calibration
projection, box 저장·재로드를 한 번 더 확인한다. Windows 실행 파일은 현재 디지털 서명되지
않았고 Linux는 Ubuntu 계열 x86_64 이외 배포판을 보장하지 않는다.

프로젝트 자체 오픈소스 라이선스는 아직 선언되지 않았다. 제3자 구성요소의 라이선스 고지는
실행 파일 또는 Linux 배포 압축에 포함된 `THIRD_PARTY_NOTICES.md`를 따른다.
