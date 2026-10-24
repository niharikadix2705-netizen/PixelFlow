FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN sed -i 's|http://archive.ubuntu.com/ubuntu|http://mirror.kakao.com/ubuntu|g; s|http://security.ubuntu.com/ubuntu|http://mirror.kakao.com/ubuntu|g' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends g++ pkg-config libopencv-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY version_check.cpp .

RUN g++ -std=c++17 version_check.cpp -o version_check \
    $(pkg-config --cflags --libs opencv4)

CMD ["./version_check"]