# LiDAR Label Tool 개발 규칙

이 저장소에서 사용자와의 대화, 진행 보고, 사용자 문서는 한국어를 기본으로 한다. 코드 식별자, 공개 API, 파일/JSON 키는 영어를 사용한다.

## 작업 원칙

1. 구현 전에 `docs/`의 확정 계약, 위험 Gate, 보류 범위를 확인한다.
2. 좌표계, 단위, yaw 정의를 암묵적으로 바꾸지 않는다.
3. UI가 파일 포맷이나 JSON 구조를 직접 다루지 않게 한다.
4. 도메인 모델은 Qt, OpenGL, OpenCV에 의존하지 않는다.
5. 새 입력 포맷은 loader 인터페이스 구현으로 추가한다.
6. 새 출력 포맷은 exporter 인터페이스 구현으로 추가한다.
7. 사용자 데이터는 원자적으로 저장하고, 실패 시 기존 라벨을 보존한다.
8. 렌더링용 다운샘플과 원본 포인트 클라우드를 구분한다.
9. 보정 파일이 없거나 잘못되어도 LiDAR 라벨링은 계속 가능해야 한다.
10. 기능 변경에는 해당 단위 테스트 또는 통합 테스트를 함께 추가한다.
11. 설치된 Python에 우연히 의존하지 않도록 배포본은 깨끗한 Windows 환경에서 검증한다.
12. 번들 내부의 기본 설정은 읽기 전용으로 취급하고 사용자 설정·로그는 사용자 쓰기 가능 경로에 둔다.
13. 여러 LiDAR를 합칠 때 calibration이 적용되지 않은 좌표를 하나의 공통 좌표처럼 취급하지 않는다.
14. 변환 행렬은 `T_target_source` 이름을 사용하고 source 좌표를 target 좌표로 바꾼다는 뜻을 유지한다.
15. 원본 source label을 직접 덮어쓰지 않고 작업 라벨과 명시적 export를 분리한다.
16. source object ID와 알 수 없는 field는 import/edit/save round-trip에서 가능한 한 보존한다.
17. background load 결과에는 request generation을 붙여 오래된 frame 결과가 최신 UI를 덮지 못하게 한다.
18. Qt/OpenGL 객체는 main thread에서만 변경하고 worker는 순수 데이터 로드·변환만 수행한다.
19. 저장 전에 source/working 파일의 fingerprint와 revision을 비교하여 외부 변경을 조용히 덮어쓰지 않는다.
20. calibration fingerprint가 달라지면 기존 라벨과의 불일치를 사용자에게 알린다.

## 코드 규칙

- Python 3.10 이상과 타입 힌트를 기준으로 한다.
- 경로는 `pathlib.Path`를 사용하며 절대 경로를 하드코딩하지 않는다.
- 데이터 모델은 가능한 한 `dataclass`와 명시적 검증을 사용한다.
- geometry 함수는 NumPy 배열의 shape, dtype, 좌표 프레임을 docstring에 명시한다.
- UI 이벤트는 service/command 계층을 호출하고 모델을 직접 저장하지 않는다.
- 예외를 무시하지 말고 사용자 메시지와 개발자 로그를 분리한다.
- 큰 포인트 클라우드는 불필요하게 복사하지 않는다.
- 긴 scan/load/export는 UI thread를 막지 않으며 progress와 cancel을 제공한다.

## 완료 기준

- 정적 검사와 테스트가 통과한다.
- 정상 경로뿐 아니라 누락 이미지, 누락 보정, 손상된 BIN/JSON을 확인한다.
- 저장 중 실패해도 기존 JSON이 손상되지 않는다.
- 동일한 객체 선택과 편집 결과가 3D, BEV, 측면, 이미지 뷰에 일관되게 반영된다.
- 배포본이 Python 미설치 Windows PC에서 실행되고 한글/공백 경로의 데이터셋을 열 수 있다.
- calibration ON/OFF 상태와 사용한 행렬이 UI와 로그에서 추적 가능하다.
- calibration이 없거나 잘못되면 잘못 정렬된 멀티 LiDAR를 조용히 합치지 않는다.
- 기존 라벨이 먼저 표시되고 편집 후 재로드해도 ID, class, box 값이 유지된다.
