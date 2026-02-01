FROM python:3.12-slim

WORKDIR /tool

ENV PYTHONUTF8=1
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

COPY pyproject.toml /tool/pyproject.toml
COPY logiclint /tool/logiclint
COPY .logiclint/logiclint.config.json /tool/.logiclint/logiclint.config.json
COPY README.md /tool/README.md

RUN pip install --no-cache-dir -e .

# runtime: mount a manuscript directory to /work
WORKDIR /work
# config 探索は CLI 側に委ねる:
# - /work/.logiclint/logiclint.config.json があればそれを優先
# - 無ければ /tool/.logiclint/logiclint.config.json（同梱）を使用
ENTRYPOINT ["logiclint"]
CMD ["--help"]

