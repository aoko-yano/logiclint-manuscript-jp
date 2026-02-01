FROM python:3.12-slim

WORKDIR /tool

ENV PYTHONUTF8=1
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

COPY pyproject.toml /tool/pyproject.toml
COPY logiclint /tool/logiclint
COPY logiclint.config.json /tool/.logiclint/logiclint.config.json
COPY README.md /tool/README.md

RUN pip install --no-cache-dir -e .

# runtime: mount a manuscript directory to /work
WORKDIR /work
ENTRYPOINT ["logiclint", "--config", "/tool/.logiclint/logiclint.config.json"]
CMD ["--help"]

