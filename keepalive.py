#!/usr/bin/env python3
"""instabox keepalive: 续 timeout + 唤醒 + 进程自愈。

规则（2026-10-19 实测）：
  - 免费档 autoSuspendAfterSeconds 被平台钉死在 1800（传 0 会被改回），空闲 30 分钟必挂起
  - timeoutSeconds 最大 14400（4h），PATCH 可续
  - 挂起态 POST /wake 返回 409，必须 POST /start
"""
import json, os, sys, time, uuid, urllib.request, urllib.error

KEY = os.environ["INSTABOX_KEY"].strip()
BASE = "https://api.instabox.sh"
PREFIX = os.environ.get("MACHINE_PREFIX", "ibox-")
TMO = int(os.environ.get("TIMEOUT_SECONDS", "14400"))
BOOT = "/data/bin/boot.sh"
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    LOG.append(s)
    print(s, flush=True)


def api(path, method="GET", body=None, timeout=90):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + KEY)
    req.add_header("Idempotency-Key", "ka-" + uuid.uuid4().hex[:16])
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return -1, {"err": str(e)[:150]}


def exec_(mid, cmd, timeout=120):
    st, r = api(f"/v1/machines/{mid}/exec", "POST", {"cmd": cmd, "timeoutSeconds": min(timeout, 600)}, timeout + 60)
    return st, (r.get("stdout") or r.get("output") or ""), (r.get("stderr") or ""), r


def main():
    st, r = api("/v1/machines")
    if st != 200:
        log("FATAL: 列机器失败", st, json.dumps(r)[:300])
        sys.exit(1)
    machines = [m for m in r.get("machines", []) if m["name"].startswith(PREFIX)]
    if not machines:
        log("没有匹配前缀的机器:", PREFIX)
        return
    problems = []
    for m in machines:
        mid, name, state = m["id"], m["name"], m["state"]
        # 1) 续命：2026-10-21 起 API 已移除 timeoutSeconds 字段（PATCH 只接受
        #    name/rootDiskGiB/persistentDiskGiB/metadata/autoSuspendAfterSeconds/vault），
        #    机器 timeoutAt 恒为 None，所以不再续期；autoSuspendAfterSeconds 仍被平台钉死 1800。
        #    实际防挂起靠下面的 exec（每 10 分钟一次活动会重置空闲计时器）。
        # 2) 不在跑就拉起来
        if state != "running":
            st, sr = api(f"/v1/machines/{mid}/start", "POST")
            log(f"{name}: {state} -> start {st}")
            if st not in (200, 202):
                problems.append(f"{name}: start {st} {json.dumps(sr)[:120]}")
                continue
            for _ in range(10):
                time.sleep(6)
                st2, m2 = api(f"/v1/machines/{mid}")
                if m2.get("state") == "running":
                    break
            state = m2.get("state", state)
        # 3) 进程自愈（只有 running 才有意义）
        if state == "running":
            st, out, err, raw = exec_(
                mid,
                "ls /data/bin/boot.sh >/dev/null 2>&1 && (bash /data/bin/boot.sh >/tmp/boot.log 2>&1; echo boot_rc=$?); "
                "pgrep -x xray >/dev/null && echo xray=up || echo xray=DOWN; "
                "pgrep -x nezha-agent >/dev/null && echo nezha=up || echo nezha=DOWN",
                90)
            tail = " ".join((out or "").split())[-160:]
            log(f"{name}: {state} | {tail}")
            if st != 200:
                problems.append(f"{name}: exec {st}")
            elif name == "ibox-01" and ("xray=DOWN" in (out or "") or "nezha=DOWN" in (out or "")):
                problems.append(f"{name}: 进程没起来 -> {tail}")
        else:
            problems.append(f"{name}: 仍是 {state}")
    if problems:
        log("PROBLEMS:", "; ".join(problems))
        sys.exit(1)
    log("all good")


if __name__ == "__main__":
    main()
