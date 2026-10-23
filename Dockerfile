FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 XDG_DATA_HOME=/data

WORKDIR /app

# pywebview (janela desktop) não é usado no servidor e exige GTK/WebKit; fica de fora da imagem
COPY requirements.txt .
RUN grep -viE '^(pywebview|pytest)' requirements.txt > requirements-server.txt \
    && pip install -r requirements-server.txt

COPY main.py ./
COPY spetr ./spetr

RUN useradd -r -u 10001 -d /data spetr && mkdir -p /data && chown spetr /data
USER spetr
VOLUME /data

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/v1/status', timeout=4)"

# --publico: painel somente leitura; a coleta real do TSE inicia sozinha ao subir
ENTRYPOINT ["python", "main.py", "--host", "0.0.0.0", "--porta", "8000", "--publico", "--db", "/data/spetr_eleicoes.sqlite"]
CMD ["--modo", "real", "--ano", "2026", "--turno", "2"]
