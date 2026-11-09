# Deployment

The service is designed to run on one VPS with Docker Compose: API, worker, bot,
PostgreSQL and Redis (see [architecture.md](architecture.md)). It is not deployed publicly
yet and runs locally for the owner's household. This page is the procedure, step by step;
every command runs on the server unless it says otherwise.

## 1. Server

- A KVM VPS (Docker needs a full kernel), Ubuntu 24.04 LTS, 2 vCPU, 2–4 GB RAM, 30 GB SSD.
- Access only with an SSH key. The owner adds the public deploy key to the root account at
  creation; the private key never leaves the machine that deploys.

## 2. Hardening

```bash
adduser --disabled-password --gecos "" deploy
usermod -aG sudo deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
cp /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
echo "deploy ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/deploy

# SSH: keys only, no root login.
sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl restart ssh

# Firewall: SSH, and HTTPS only if the API is exposed (section 5).
apt-get update && apt-get install -y ufw unattended-upgrades
ufw default deny incoming && ufw default allow outgoing
ufw allow OpenSSH
ufw enable
dpkg-reconfigure -f noninteractive unattended-upgrades
```

Check from a second terminal that `ssh deploy@<server>` works before closing the first.

## 3. Docker and the code

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker deploy          # log out and in again
sudo install -d -o deploy -g deploy /opt/family-pnl
git clone https://github.com/R00tPengu1n/family-pnl.git /opt/family-pnl
cd /opt/family-pnl
cp .env.example .env && chmod 600 .env
```

The owner fills `.env` on the server: `POSTGRES_PASSWORD`, `FAMILY_PNL_JWT_SECRET`,
`FAMILY_PNL_BOT_API_SECRET` (random, 32+ characters each:
`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`) and
`FAMILY_PNL_TELEGRAM_BOT_TOKEN`. Secrets live only in this file.

## 4. Start, and survive a reboot

```bash
docker compose up --build -d
curl http://127.0.0.1:8000/health       # {"status":"ok","database":"ok"}
```

Every service has `restart: unless-stopped` and Docker starts on boot, so the stack comes
back after `sudo reboot`; check `/health` and send `/start` to the bot afterwards.
The API listens on 127.0.0.1 only: the bot and the worker reach it inside the Compose
network, so nothing but SSH needs to be open.

## 5. HTTPS (only if the API is used from outside the server)

Put a reverse proxy in front with a domain pointing at the server, e.g. Caddy, which gets
certificates itself:

```bash
sudo apt-get install -y caddy
echo 'api.example.org {
    reverse_proxy 127.0.0.1:8000
}' | sudo tee /etc/caddy/Caddyfile
sudo systemctl reload caddy
sudo ufw allow 443/tcp && sudo ufw allow 80/tcp
```

Behind a proxy the API must see real client IPs for the login rate limit (ADR-0006),
otherwise every login shares one address and five failures lock everyone out. uvicorn
reads `X-Forwarded-For` (`--proxy-headers` is on by default) only from the addresses in
`FORWARDED_ALLOW_IPS`, which `docker-compose.yml` passes from `.env`; the default,
`127.0.0.1,::1`, trusts nobody but the container itself.

Caddy on the host connects to the published port, so inside the container its requests
come from the gateway of the Compose network, not from 127.0.0.1. `docker-compose.yml`
pins that network to `172.30.0.0/24` with the gateway `172.30.0.1`; trust exactly that
address:

```bash
nano .env                    # FORWARDED_ALLOW_IPS=172.30.0.1
docker compose up -d api     # recreates the api container with the new value
```

A stack started before the subnet was pinned keeps its old network: run
`docker compose down` and `docker compose up -d` once (the volumes and the data stay). If
`172.30.0.0/24` clashes with another network on the server ("Pool overlaps"), change the
subnet and the gateway in `docker-compose.yml` and `FORWARDED_ALLOW_IPS` together.

Keep `API_BIND` at `127.0.0.1`: with the port open to the internet, some clients'
connections (those Docker relays through its userland proxy) would also arrive from the
gateway and could set the header themselves. If Caddy runs as a service in the same
Compose file instead, trust the address of its container.

## 6. Backups

`scripts/backup.sh` dumps PostgreSQL (`pg_dump -Fc`) to `backups/daily/` every day, copies
Sunday's dump to `backups/weekly/`, and keeps the 7 newest daily and 4 newest weekly dumps.

```bash
mkdir -p /opt/family-pnl/backups
crontab -e
# 30 3 * * * cd /opt/family-pnl && scripts/backup.sh >> backups/backup.log 2>&1
```

Copy the dumps off the server as well (they are the only copy if the disk is lost), e.g.
from the owner's machine: `scp -r deploy@<server>:/opt/family-pnl/backups ./family-pnl-backups`.

### Restore

Into a scratch database first, to check the dump:

```bash
scripts/restore.sh backups/daily/family_pnl-2026-10-25.dump
# restore: ... -> family_pnl_restore, schema <revision>, <n> operations
```

Replacing the live database:

```bash
docker compose stop api worker bot
scripts/restore.sh backups/daily/family_pnl-2026-10-25.dump family_pnl
docker compose up -d
```

Checked on 2026-10-25 against the local Compose stack: a dump of 3 operations restored with
the same schema revision and 3 operations; rotation kept the 7 newest daily dumps.

## 7. Updating

Until continuous deployment exists (task 36):

```bash
cd /opt/family-pnl
git pull
docker compose up --build -d            # migrate runs before api and worker start
```

Migrations run in one transaction before the API and the worker start. A failed migration
leaves the schema at its previous revision; `docker compose up` exits with an error and
does not start the API, the worker and the bot, which depend on `migrate`. Check
`docker compose ps -a` for what is running and `docker compose logs migrate` for why it
failed; then fix the migration (or check out the previous commit) and run
`docker compose up --build -d` again.
