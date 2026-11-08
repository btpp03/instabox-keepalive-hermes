#!/usr/bin/env python3
"""instabox keepalive: 唤醒 + 按机器进程自愈。

规则（2026-10-19 实测）：
  - 免费档 autoSuspendAfterSeconds 被平台钉死在 1800（传 0 会被改回），空闲 30 分钟必挂起
  - 挂起态 POST /wake 返回 409，必须 POST /start
  - 挂起时进程被冻结保留（processesPreserved），唤醒后 TCP 是死连接，
    所以刚 start 回来的那轮要强制重启 01 的 nezha-agent，不能只做幂等 pgrep
2026-11-08：覆盖 ibox-01(哪吒) + ibox-03(hermes)。01 只拉 nezha-agent，不跑 xray。
"""
import json, os, sys, time, uuid, urllib.request, urllib.error

KEY = os.environ["INSTABOX_KEY"].strip()
BASE = "https://api.instabox.sh"
# 只保活这两台；02/04/05 不挂服务，不拉起
WANTED = set(x.strip() for x in os.environ.get("MACHINES", "ibox-01,ibox-03").split(",") if x.strip())
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
    machines = [m for m in r.get("machines", []) if m["name"] in WANTED]
    if not machines:
        log("没有匹配名字的机器:", ",".join(sorted(WANTED)))
        return
    problems = []
    for m in machines:
        mid, name, state = m["id"], m["name"], m["state"]
        just_started = False
        # 1) 续命：2026-10-21 起 API 已移除 timeoutSeconds 字段（PATCH 只接受
        #    name/rootDiskGiB/persistentDiskGiB/metadata/autoSuspendAfterSeconds/vault），
        #    机器 timeoutAt 恒为 None，所以不再续期；autoSuspendAfterSeconds 仍被平台钉死 1800。
        #    实际防挂起靠下面的 exec（每 10 分钟一次活动会重置空闲计时器）。
        # 2) 不在跑就拉起来
        if state != "running":
            st, sr = api(f"/v1/machines/{mid}/start", "POST")
            log(f"{name}: {state} -> start {st}")
            if st in (200, 202):
                just_started = True  # 唤醒后连接僵死，下面要强制重连
            if st not in (200, 202):
                problems.append(f"{name}: start {st} {json.dumps(sr)[:120]}")
                continue
            for _ in range(10):
                time.sleep(6)
                st2, m2 = api(f"/v1/machines/{mid}")
                if m2.get("state") == "running":
                    break
            state = m2.get("state", state)
        # 3) 进程自愈（只有 running 才有意义），按机器分派
        if state == "running":
            if name == "ibox-01":
                # boot.sh 只拉 nezha-agent（已不含 xray）；刚唤醒则强制重连
                pre = "pkill -x nezha-agent 2>/dev/null; sleep 2; " if just_started else ""
                cmd = (pre + "bash /data/bin/boot.sh >/tmp/boot.log 2>&1; echo boot_rc=$?; "
                       "sleep 3; pgrep -x nezha-agent >/dev/null && echo nezha=up || echo nezha=DOWN")
                down = "nezha=DOWN"
            else:  # ibox-03: hermes gateway
                cmd = ("bash /data/home/hermes/start_hermes.sh >/tmp/boot.log 2>&1; echo hermes_rc=$?; "
                       "pgrep -f hermes >/dev/null && echo hermes=up || echo hermes=DOWN")
                down = "hermes=DOWN"
            st, out, err, raw = exec_(mid, cmd, 90)
            tail = " ".join((out or "").split())[-160:]
            log(f"{name}: {state} | {tail}")
            if st != 200:
                problems.append(f"{name}: exec {st}")
            elif down in (out or ""):
                problems.append(f"{name}: 进程没起来 -> {tail}")
        else:
            problems.append(f"{name}: 仍是 {state}")
    if problems:
        log("PROBLEMS:", "; ".join(problems))
        sys.exit(1)
    log("all good")


if __name__ == "__main__":
    main()
