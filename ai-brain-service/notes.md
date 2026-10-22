
podman build -t gateway-ai-brain .

# To see your current networks
podman network ls

# Run the brain on your existing network (e.g., 'jhipster-network')
podman run -d --name ai-brain \   
-p 8000:8000 \
--network=gateway_service_default \
gateway-ai-brain


podman ps

podman logs ai-brain


### Recreate the .venv

python3 -m venv .venv

### pip ativate
source .vevn/bin/activate

### install in requirements
pip install -r requirements.txt


### Run the server
uvicorn app:app --reload --port 8000

http://localhost:8000/docs