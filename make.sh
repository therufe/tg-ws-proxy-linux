#!/bin/bash

IMAGE_NAME="tgwsproxy-builder"

cat <<EOF > Dockerfile.build
FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-dev \
    patchelf desktop-file-utils wget fuse file \
    g++ ccache \
    libxcb-cursor0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --upgrade pip nuitka psutil Pillow cryptography PyQt6

# раскомментировать если сборка производится на арче, debian-based системам не требуется
# RUN python3 -c "import nuitka.utils.Timing as T; p = T.__file__.replace('.pyc', '. py'); data = open(p, 'r', encoding='utf-8').read(); open(p, 'w', encoding='utf-8').write(data.replace('PerfCounters() if use_perf_counters else None', 'None'))"

RUN wget -q https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage \
    && mv appimagetool-x86_64.AppImage /usr/local/bin/appimagetool \
    && chmod +x /usr/local/bin/appimagetool
WORKDIR /build
EOF

docker build -t $IMAGE_NAME -f Dockerfile.build .

docker run --rm --privileged -v $(pwd):/build $IMAGE_NAME /bin/bash -c "

    # сборка через Nuitka
    python3 -m nuitka --standalone \
        --plugin-enable=pyqt6 \
        --include-data-dir=src/resources=resources \
        --output-dir=dist \
        src/main.py

    # копирование бинарника в AppDir
    mkdir -p AppDir/usr/bin
    cp -r dist/main.dist/* AppDir/usr/bin/
    mv AppDir/usr/bin/main.bin AppDir/usr/bin/tgwsproxy
    chmod +x AppDir/usr/bin/tgwsproxy

    # add libxcb-cursor0
    cp -L /usr/lib/x86_64-linux-gnu/libxcb-cursor.so.0 AppDir/usr/bin/

    mkdir -p AppDir/usr/bin/resources
    cp src/resources/icon.png AppDir/usr/bin/resources/icon.png

    # копируем иконку
    cp src/resources/icon.png AppDir/icon.png
    mkdir -p AppDir/usr/share/icons/hicolor/256x256/apps
    cp src/resources/icon.png AppDir/usr/share/icons/hicolor/256x256/apps/tgwsproxy.png

    # .desktop
    echo '[Desktop Entry]' > AppDir/tgwsproxy.desktop
    echo 'Name=tgwsproxy' >> AppDir/tgwsproxy.desktop
    echo 'Exec=tgwsproxy' >> AppDir/tgwsproxy.desktop
    echo 'Icon=icon' >> AppDir/tgwsproxy.desktop
    echo 'Type=Application' >> AppDir/tgwsproxy.desktop
    echo 'Categories=Network;' >> AppDir/tgwsproxy.desktop

    # AppRun
    echo '#!/bin/sh' > AppDir/AppRun
    echo ''
    echo 'exec \"\$(dirname \"\$0\")/usr/bin/tgwsproxy\"' >> AppDir/AppRun
    chmod +x AppDir/AppRun

    # упаковка
    ARCH=x86_64 appimagetool AppDir tgwsproxy-x86_64.AppImage

    # чистка
    rm -rf dist build AppDir
"
