# 901-proactive

## Setting the project after new checkout
```shell
python3 -m venv .venv
source .venv/bin/activate  
pip install -r requirements.txt  
```

## How to run ai-brain-service
```shell
uvicorn app:app --reload --port 8000
```