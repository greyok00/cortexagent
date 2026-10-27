FROM python:3.13-slim
COPY cortexagent-*.whl /tmp/
RUN pip install --no-cache-dir /tmp/cortexagent-*.whl && rm -f /tmp/*.whl
ENTRYPOINT ["cortexagent"]