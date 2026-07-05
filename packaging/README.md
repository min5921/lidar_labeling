# Packaging

이 폴더에는 구현 후 다음 재현 가능한 배포 자료를 둔다.

- `pysidedeploy.spec`
- Windows build 설정
- installer 설정(채택 시)
- version metadata
- third-party license 목록 생성 설정

빌드 결과물은 이 폴더에 넣지 않고 Git에서 제외된 `release/`에 생성한다. spec은 절대 경로나 개발자 PC의 사용자명을 포함하면 안 된다.
