FROM python:3.12-slim

WORKDIR /app
COPY requirements-cloud-run.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY cgv_imax_telegram.py .

ENV PYTHONUNBUFFERED=1
ENV RUN_ONCE=1
CMD ["python", "cgv_imax_telegram.py"]
