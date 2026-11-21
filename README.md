# Alcohol Tracker

A small Flask app for recording alcohol units, checking the total consumed in the last 24 hours, and viewing a 14-day daily trend. Entries are stored in a local SQLite database and can be edited or deleted.

## Run locally

Requires Python 3.10 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). The database is created automatically at `instance/alcohol-tracker.sqlite3`.

## Test

```bash
python -m unittest discover -s tests
```

## Run with Docker Desktop

Start Docker Desktop, then run these commands from the repository directory:

```bash
docker build -t booz-tracker:local .
docker volume create alcohol-tracker-data
docker run -d --name alcohol-tracker --restart unless-stopped \
  -p 127.0.0.1:80:8000 \
  -e SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')" \
  --mount type=volume,source=alcohol-tracker-data,target=/data \
  booz-tracker:local
```

Open [http://localhost](http://localhost). Docker Desktop shows the running container as `alcohol-tracker`; use `docker stop alcohol-tracker` and `docker start alcohol-tracker` to stop and restart it. The named volume keeps entries when the container is restarted or replaced. If port 80 is already in use, publish `127.0.0.1:8080:8000` instead and open `http://localhost:8080`. For a dedicated hostname instead of `localhost`, configure that name to resolve to `127.0.0.1` on the Mac.

## Run in Kubernetes

The container runs Gunicorn as a non-root user. Kubernetes stores the SQLite database on a 1 GiB persistent volume claim and runs one pod at a time; SQLite is intended for this single-instance setup. The manifest creates a private `ClusterIP` service. Use your cluster's Ingress or Gateway configuration if you need external access.

Build and push the image to a registry your cluster can pull from. Update the image in `k8s/manifest.yaml` if you use a different image name or tag:

```bash
docker build -t ghcr.io/redtlarsen/booz-tracker:latest .
docker push ghcr.io/redtlarsen/booz-tracker:latest
```

Create the namespace and a persistent Flask signing key, then apply the workload:

```bash
kubectl create namespace alcohol-tracker
kubectl create secret generic alcohol-tracker-secret \
  --namespace alcohol-tracker \
  --from-literal=secret-key="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
kubectl apply -f k8s/manifest.yaml
kubectl rollout status deployment/alcohol-tracker --namespace alcohol-tracker
```

The claim uses your cluster's default StorageClass. If there is no default, set `spec.storageClassName` in the claim to a class available in your cluster. Access the app locally with:

```bash
kubectl port-forward --namespace alcohol-tracker service/alcohol-tracker 8080:80
```

Then open [http://127.0.0.1:8080](http://127.0.0.1:8080). Back up the `alcohol-tracker-data` PVC to preserve records. Keep one replica: this app uses SQLite and is not designed for horizontal scaling.
