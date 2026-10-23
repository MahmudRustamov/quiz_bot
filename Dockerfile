FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1
WORKDIR /app
COPY pyproject.toml ./
COPY quizbot ./quizbot
RUN pip install --no-cache-dir . && useradd --create-home --uid 10001 quiz && mkdir /app/results && chown quiz:quiz /app/results
COPY alembic.ini ./
COPY migrations ./migrations
COPY examples ./examples
COPY exams ./exams
USER quiz
CMD ["python", "-m", "quizbot"]
