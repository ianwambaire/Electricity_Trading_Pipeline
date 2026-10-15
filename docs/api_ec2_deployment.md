# PowerFlow API deployment on EC2

The PowerFlow FastAPI application is a separate, read-only service. Uvicorn
listens only on `127.0.0.1:8000`; Nginx is the sole public entry point and
publishes it beneath the existing HTTPS `/api/` path. Do not add port 8000 to
the EC2 security group or host firewall. This deployment does not replace or
modify the existing Streamlit, Prefect server, or Prefect worker services.

## Install or update the service

After pulling reviewed changes, update the production environment and verify
the application's imports:

```bash
cd /home/ec2-user/Electricity_Trading_Pipeline
source .venv-prod/bin/activate
python -m pip install --only-binary=:all: -r requirements-prod.txt
python scripts/check_production_imports.py
```

Install the unit as root-owned configuration, then enable and start it:

```bash
sudo install -o root -g root -m 0644 \
  deploy/powerflow-api.service \
  /etc/systemd/system/powerflow-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now powerflow-api.service
sudo systemctl status powerflow-api.service
```

The unit runs as `ec2-user`, uses the production virtual environment, sets
`PYTHONPATH` to the repository's `src` directory, and restarts after a failure.
It deliberately does not load `.env`: the read-only API reads existing local
reports and operational metadata and does not need production credentials.
Logs are available through the systemd journal:

```bash
sudo journalctl -u powerflow-api.service -n 100 --no-pager
sudo journalctl -u powerflow-api.service -f
```

## Add the Nginx route

The tracked file `deploy/nginx/powerflow-api-location.conf` is a location-only
snippet. Install it, then include it **inside the existing HTTPS `server` block**
before the current Streamlit `location /` block:

```bash
sudo install -d -o root -g root -m 0755 /etc/nginx/snippets
sudo install -o root -g root -m 0644 \
  deploy/nginx/powerflow-api-location.conf \
  /etc/nginx/snippets/powerflow-api-location.conf
```

Add this one line to the existing TLS server block:

```nginx
include /etc/nginx/snippets/powerflow-api-location.conf;
```

The resulting routing within the existing HTTPS server should conceptually be:

```nginx
server {
    listen 443 ssl;
    # Existing server_name, certificates, and TLS settings remain unchanged.

    include /etc/nginx/snippets/powerflow-api-location.conf;

    location / {
        # Existing Streamlit proxy configuration remains unchanged.
    }
}
```

Do not edit the existing port-80 HTTP-to-HTTPS redirect. The snippet forwards
`/api/health` to `http://127.0.0.1:8000/health` and supplies `Host`,
`X-Real-IP`, `X-Forwarded-For`, and `X-Forwarded-Proto`. It adds no CORS
headers and does not change authentication.

Validate the complete installed Nginx configuration before applying it. Reload
only after validation succeeds:

```bash
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl status nginx
```

If `nginx -t` fails, leave the currently running configuration in place, fix
the reported syntax or include location, and validate again before reloading.

## Deployment validation checklist

Run these checks after every install or update:

```bash
# API process and logs
sudo systemctl status powerflow-api.service
sudo journalctl -u powerflow-api.service -n 100 --no-pager

# Uvicorn is reachable locally and bound only to loopback
curl --fail --silent --show-error http://127.0.0.1:8000/health
sudo ss -ltnp | grep ':8000'

# Public traffic reaches FastAPI only through Nginx HTTPS
curl --fail --silent --show-error https://YOUR_POWERFLOW_HOST/api/health

# Existing Streamlit route and Prefect worker remain healthy
curl --fail --silent --show-error --head https://YOUR_POWERFLOW_HOST/
sudo systemctl is-active powerflow-streamlit.service
sudo systemctl is-active powerflow-prefect-worker.service
```

The `ss` output must show `127.0.0.1:8000`, never `0.0.0.0:8000` or
`[::]:8000`. From a machine outside the EC2 instance, the following direct-port
check must fail while the HTTPS check above succeeds:

```bash
curl --connect-timeout 5 http://EC2_PUBLIC_IP:8000/health
```

Also confirm that the EC2 security group has no inbound TCP rule for port 8000.
The existing Streamlit homepage must continue to render through its current
Nginx route, and `powerflow-prefect-worker.service` must remain active.

## Routine operations and rollback

Restart only the API after application updates:

```bash
sudo systemctl restart powerflow-api.service
sudo systemctl status powerflow-api.service
```

If the API route must be rolled back, remove or comment only the snippet include
from the HTTPS server block, run `sudo nginx -t`, and reload Nginx. This leaves
the existing Streamlit and HTTPS redirect configuration intact. The API service
can then be stopped with:

```bash
sudo systemctl disable --now powerflow-api.service
```
