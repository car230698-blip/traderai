FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY traderai ./traderai
RUN chmod -R a+rX /app && pip install --no-cache-dir . && useradd --create-home traderai && mkdir /data && chown traderai:traderai /data
USER traderai
ENV TRADERAI_DB_PATH=/data/workspace.db
EXPOSE 8000
ENTRYPOINT ["python", "-m", "traderai.server"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
