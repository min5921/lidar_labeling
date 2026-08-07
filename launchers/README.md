# 실행 파일

사용자용 설치·실행 파일은 이 폴더에서 관리한다. 모든 스크립트는 자신의 위치를 기준으로
저장소 루트를 찾으므로, 탐색기에서 더블클릭하거나 저장소 루트에서 실행할 수 있다.

## Windows

- 최초 설치 또는 의존성 갱신: `windows/setup_windows.bat`
- 라벨링 도구 실행: `windows/run_windows.bat`

## Linux

- 최초 설치 또는 의존성 갱신: `linux/setup_linux.sh`
- 라벨링 도구 실행: `linux/run_linux.sh`

`legacy/run_merged_sample.bat`은 예전 merged 샘플 전용이므로 일반 데이터셋에는 사용하지
않는다.

개발·검증·패키징 자동화는 저장소 루트가 아니라 `scripts/`와 `packaging/`에서 관리한다.
