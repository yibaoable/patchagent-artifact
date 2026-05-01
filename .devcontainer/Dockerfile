FROM ubuntu:24.04

RUN apt-get update && apt-get install -y gdb wget build-essential python3 net-tools python3-pip git ninja-build libxml2-dev default-jdk libxslt1-dev libarchive-dev curl libssl-dev libcurl4-openssl-dev universal-ctags clang cmake ninja-build autoconf rake autogen libtool shtool libcunit1 libcunit1-doc libcunit1-dev ragel zlib1g-dev libbz2-dev liblzma-dev pkg-config python-is-python3 autopoint bison flex gawk gettext make libaudit-dev libcap-dev libcap-ng-dev libglib2.0-dev libpcre2-dev tmux clangd libtasn1-6-dev bear time libjpeg-dev texinfo nasm  gperf rsync tidy bsdmainutils libbrotli-dev libinih-dev xmlto python3-tk gcc-11 bc flex debootstrap qemu-system expect libelf-dev pahole sudo libfuse-dev libnuma-dev libmnl-dev cpio git-lfs clang-16 golang

RUN apt-get install -y python3.12-venv && python3 -m venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"

RUN pip install python-dotenv GitPython  pika meson pandas openpyxl clang==16.0.1 unidiff  litellm prettytable matplotlib venn langchain==0.2.5 langchain-community==0.2.5 langchain-core==0.2.9 langchain-experimental==0.0.61 langchain-openai==0.1.8 openai==1.35.1

ENV LC_CTYPE C.UTF-8
ENV LANG C.UTF-8

RUN echo "yes" | apt-get install msttcorefonts -y -qq && rm ~/.cache/matplotlib -fr

COPY patchagent-artifact/ /workspace/