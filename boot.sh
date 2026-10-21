#!/bin/bash
# 幂等启动：xray + nezha-agent
pgrep -x xray >/dev/null || (cd /data/xray && setsid bash -c "exec ./xray run -c config.json >> /data/xray/xray.log 2>&1" </dev/null >/dev/null 2>&1 &)
if [ -x /data/nezha/nezha-agent ] && [ -s /data/nezha/secret.txt ]; then
  pgrep -x nezha-agent >/dev/null || (cd /data/nezha && setsid bash -c "exec ./nezha-agent -s nezhak2.btpp.ggff.net:443 -p $(cat /data/nezha/secret.txt) --tls --disable-auto-update --disable-force-update >> /data/nezha/agent.log 2>&1" </dev/null >/dev/null 2>&1 &)
fi
