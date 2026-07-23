# LiDAR Label Tool Linux 0.2.2

## 지원 환경

- Ubuntu 22.04 LTS 또는 그 이후의 x86_64 데스크톱
- X11 또는 XWayland를 제공하는 데스크톱 세션
- OpenGL을 제공하는 그래픽 드라이버

Python, pip, ROS2, PowerShell은 설치하지 않는다.

## 실행

터미널에서 압축을 풀고 실행한다.

```bash
tar -xzf LiDARLabelTool_Integrated_0.2.2_linux_x86_64.tar.gz
cd LiDARLabelTool_Integrated_0.2.2_linux_x86_64
./LiDARLabelTool
```

파일 관리자에서 `LiDARLabelTool`을 더블클릭해도 된다. 배포판 설정에 따라 처음 한 번
"프로그램으로 실행" 권한을 허용해야 할 수 있다.

## 시스템 라이브러리 오류

일반적인 Ubuntu 데스크톱에는 대부분 설치되어 있다. Qt xcb/OpenGL 라이브러리 오류가 나면 다음을
설치한다.

```bash
sudo apt update
sudo apt install \
  libdbus-1-3 libegl1 libfontconfig1 libgl1 libglib2.0-0 libice6 libopengl0 \
  libsm6 libx11-6 libx11-xcb1 libxcb1 libxcb-cursor0 libxcb-glx0 \
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
  libxcb-render-util0 libxcb-shape0 libxcb-shm0 libxcb-sync1 libxcb-util1 \
  libxcb-xfixes0 libxcb-xinerama0 libxcb-xkb1 libxext6 libxi6 \
  libxkbcommon-x11-0 libxrender1
```

로그:

```text
${XDG_STATE_HOME:-$HOME/.local/state}/LiDARLabelTool/logs/LiDARLabelTool_crash.log
```

최근 경로 설정:

```text
${XDG_CONFIG_HOME:-$HOME/.config}/LiDARLabelTool/settings.ini
```

원본 MCAP/YAML과 변환 dataset은 실행 파일 밖에서 사용자가 원하는 경로에 둔다.
