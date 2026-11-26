FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN pip install --no-cache-dir websockets==16.0 \
    && useradd --system --uid 10001 --create-home paper \
    && mkdir /state && chown paper /state
COPY live/ ./live/
COPY spot_data.py paxg_edge_v2.py paxg_research.py technical_paper.py ./
USER paper
ENV PAPER_DB=/state/paper.sqlite3
VOLUME ["/state"]
ENTRYPOINT ["python", "-m", "live"]
CMD ["--mode", "paper"]
