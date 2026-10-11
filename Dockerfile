FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SMAGA_SKIP_NUMBAS=1 SMAGA_NO_BROWSER=1
WORKDIR /app
RUN pip install --no-cache-dir 'qrcode[pil]==8.2'
COPY . /app
# Fail build (rather than serving a broken exam) if the official Numbas
# runtime cannot be retrieved. Cache must be checked or runtime vendored
# after a successful build for reliable production rollouts.
RUN python bootstrap_numbas.py
EXPOSE 10000
CMD ["python", "server.py"]
