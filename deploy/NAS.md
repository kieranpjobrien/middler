# Running middler on the Synology NAS

middler is deployed at **`/volume1/docker/middler`** on the NAS (192.168.4.42) and
runs under Container Manager (Docker) via `docker-compose`, restart-always, so it
survives reboots and records uninterrupted for the forward-test.

Docker requires **root** on Synology, so the commands below use `sudo`.

## First launch

```bash
cd /volume1/docker/middler
sudo ./deploy/nas-deploy.sh        # builds the image, starts middler + redis
```

The stack starts immediately. Until API keys are present it idles and warns
(records nothing). Add at least the two free keys to begin recording:

```bash
cd /volume1/docker/middler
vi .env                            # set THE_ODDS_API_KEY and ODDS_API_IO_KEY
sudo docker-compose restart middler
```

## Day-to-day

```bash
cd /volume1/docker/middler
sudo docker-compose ps                       # status
sudo docker-compose logs -f middler          # follow logs
sudo docker-compose exec middler uv run middler-healthcheck   # quotes recorded so far
```

## Viewing the data

The app **auto-rewrites the HTML report every hour** (`backcast.report_interval_sec`
in `config.yaml`) to the bind-mounted `reports/` folder, so a current copy always
sits on the NAS share. To view it from Windows, just open:

```
\\KieranNAS\docker\middler\reports\backcast.html
```

(or run `deploy\view-report.cmd` — double-click or pin it). If `KieranNAS` doesn't
resolve, use `\\192.168.4.42\docker\middler\reports\backcast.html`.

To force a refresh on demand:

```bash
cd /volume1/docker/middler && sudo docker-compose exec middler uv run middler-report
```

The `data/`, `logs/`, and `reports/` folders are bind-mounted from
`/volume1/docker/middler`, so the DuckDB history and reports persist on the NAS
and are reachable over the share.

## Update to new code

From the dev machine, re-push the tree and rebuild:

```bash
# on the dev machine (D:\Bets)
git archive --format=tar HEAD | ssh nas 'tar xf - -C /volume1/docker/middler'
# on the NAS
cd /volume1/docker/middler && sudo ./deploy/nas-deploy.sh
```

## Stop / remove

```bash
cd /volume1/docker/middler
sudo docker-compose down            # stop (keeps data)
```

## Notes
- **Outbound-only**: no ports are published, so nothing is exposed on your LAN/WAN.
- **Backups**: `sudo docker-compose exec middler uv run middler-backup --dest /volume1/backups/middler`
  copies the DuckDB history + config; point a DSM scheduled task at it for nightlies.
- Keep `PLACEMENT_ENABLED=false` in `.env` — this box only records and alerts.
