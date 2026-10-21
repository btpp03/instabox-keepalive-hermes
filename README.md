# instabox 保活（5 × 4C8G 免费沙箱）

**平台**：https://instabox.sh （btpp04@gmail.com）
**机器**：`ibox-01` … `ibox-05`（前缀 `ibox-`），每台 4 vCPU / 8 GB / 20 GB `/data`

## 平台硬限制（2026-10-19 实测）

| 项 | 实测值 | 结论 |
|---|---|---|
| `autoSuspendAfterSeconds` | 创建时传 `0`（永不挂起）被平台**改写回 1800** | 空闲 30 分钟必挂起，关不掉 |
| `timeoutSeconds` | **2026-10-21 起被平台移除**：`PATCH` 只接受 `name/rootDiskGiB/persistentDiskGiB/metadata/autoSuspendAfterSeconds/vault`，传 `timeoutSeconds` 直接 `400 nothing to change`；机器 `timeoutAt` 恒为 `None` | 不用再续期，4h 上限已成历史 |
| 挂起后的 `wake` | `POST /v1/machines/{id}/wake` → **409** | 必须 `POST /start` |
| 地区 | 不可选，只有 AWS us-west-2（Oregon） | `pool` 是 admin 字段 |
| 出口 | 5 台共用同一 NAT IP（会变：34.213.184.41 → 44.242.204.185） | 节点只能靠域/端口区分 |

## 保活链路

1. **cron-job.org** job **8677572**（`instabox-keepalive-dispatch`）每 10 分钟 `POST` 本仓 workflow `dispatch`
   - 用户账号的 GA 原生 `schedule` 基本不 fire，所以定时靠这条外腿
   - ⚠️ cron-job.org **会静默丢掉 `Authorization` 头**（执行回 403）。必须用 job 级 HTTP Basic：
     `auth={"enable":true,"user":"btpp03","password":"<PAT>"}`（字段名是 **user**，不是 username）
   - 实测闭环：`status=1 httpStatus=204`，GA run 20 秒后创建、success
2. **GitHub Actions** `.github/workflows/keepalive.yml` → `keepalive.py`
   - 列出所有 `ibox-` 前缀机器
   - 状态不是 `running` → `POST /start` 并等它起来
   - `exec` 进机器跑 `/data/bin/boot.sh`（存在才跑）→ 幂等补 `xray` / `nezha-agent`，并保证**只有一个实例**（同 secret 双 agent 会互顶掉线）

## 机器 01 上跑的负载

- **Xray 26.3.27** VLESS+WS+TLS：`listen 0.0.0.0:8080`，path `/ray`
  公网口 = `https://8080-<machineId>.instabox.tech`（平台边缘终止 TLS，真证书）
- **哪吒 agent v0.20.5**（面板 v0.17.9 只认这个组合）
  `-s nezhak2.btpp.ggff.net:443 -p <secret> --tls --disable-auto-update --disable-force-update`
  ⚠️ 必须带 `--tls`，否则 `http2: frame too large`
- 两者都在 `/data/bin/boot.sh` 里幂等启动（`setsid` 脱离 exec 会话，否则进程会被平台随会话回收）

节点链接与 API key 只在本地 `/root/ibox/NODE.txt`（chmod 600），**不入库**——本仓是公开仓，凭据走 Actions secret `INSTABOX_KEY`。
