#!/bin/sh
# Daily pg_dump, keeps 14 days. Copy ./backups off the host (e.g. object storage) for disaster recovery.
set -eu
while true; do
  ts=$(date -u +%Y%m%dT%H%M%SZ)
  pg_dump -h db -U copytrader -d copytrader -Fc -f "/backups/copytrader-$ts.dump" && echo "backup ok $ts"
  find /backups -name 'copytrader-*.dump' -mtime +14 -delete
  sleep 86400
done
