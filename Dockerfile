FROM python:3.12-slim

WORKDIR /src
COPY ["./", "./"]

RUN pip install --no-cache-dir requests -r requirements.txt

CMD ["python","bot.py"]