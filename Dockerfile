FROM python:3.12-slim

WORKDIR /work

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY experiments/ ./experiments/
COPY tests/ ./tests/

ENV PYTHONPATH=/work

CMD ["python3", "experiments/run_all.py", "--symbols", "SPY,AAPL,BTC-USD,GLD,EURUSD=X", "--years", "6", "--out", "results"]
