#!/usr/bin/env python3
"""把 assets/ 下的 SVG 光栅化成 PNG（可选工具，不影响测试与运行）。

为什么要它：og:image、GitHub social preview、掘金/腾讯云文章封面都要 **PNG/JPG**，
社交平台基本不认 SVG。SVG 是这些图的**唯一真源**（可编辑、可 diff、纯文本），
PNG 是它的派生产物 —— 所以 `demo/og.png` 会提交进仓库，失效时重跑本脚本即可。

用法（**必须用装了 websocket-client 的解释器**）：
    C:/Users/jknight/.workbuddy/binaries/python/envs/default/Scripts/python.exe \
        tools/render_assets.py

    只渲染某一张：
    ... python.exe tools/render_assets.py --only og-card

   看草稿（输出到 assets/_preview/，不覆盖 demo/og.png）：
    ... python.exe tools/render_assets.py --preview

依赖：本机 Chrome（`_CHROME` 可改）+ websocket-client。
和 build_demo.py 一样是"构建期工具"，仓库运行本身零依赖。
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import websocket  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
_CHROME = r"C:/Program Files/Google/Chrome/Application/chrome.exe"
PORT = 9334

# 源 SVG → 目标 PNG（+ 尺寸）。目标为 None 表示只做预览、不落地到仓库。
JOBS = [
    ("og-card.svg", ROOT / "demo" / "og.png", 1200, 630),
    ("fig-scene-ranking.svg", None, 1040, 620),
    ("fig-coverage.svg", None, 1040, 620),
]


class CDP:
    def __init__(self, url: str):
        self.ws = websocket.create_connection(url, suppress_origin=True, timeout=30)
        self.i = 0

    def send(self, method: str, params: dict | None = None, session: str = "") -> dict:
        self.i += 1
        msg: dict = {"id": self.i, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        self.ws.send(json.dumps(msg))
        while True:
            got = json.loads(self.ws.recv())
            if got.get("id") == self.i:
                if "error" in got:
                    raise RuntimeError(f"{method} -> {got['error']}")
                return got.get("result", {})


def launch() -> subprocess.Popen:
    return subprocess.Popen(
        [
            _CHROME,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--remote-debugging-port={PORT}",
            "--remote-allow-origins=*",
            "--user-data-dir=" + str(Path.home() / ".cache/cdp-render"),
            "--no-first-run",
            "--force-device-scale-factor=1",
            "--window-size=1400,900",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def render(browser: CDP, svg: Path, out: Path, w: int, h: int) -> int:
    page = None
    for _ in range(40):
        targets = browser.send("Target.getTargets")["targetInfos"]
        page = next((t for t in targets if t["type"] == "page"), None)
        if page:
            break
        time.sleep(0.25)
    if page is None:
        raise RuntimeError("没找到 page target")

    sid = browser.send(
        "Target.attachToTarget", {"targetId": page["targetId"], "flatten": True}
    )["sessionId"]
    browser.send("Page.enable", session=sid)
    browser.send("Emulation.setDeviceMetricsOverride",
                 {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": False}, session=sid)
    browser.send("Page.navigate", {"url": svg.as_uri()}, session=sid)
    time.sleep(1.2)

    res = browser.send(
        "Page.captureScreenshot",
        {"format": "png", "captureBeyondViewport": True,
         "clip": {"x": 0, "y": 0, "width": w, "height": h, "scale": 1}},
        session=sid,
    )
    data = base64.b64decode(res["data"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return len(data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="只渲染文件名前缀匹配的源（如 og-card）")
    ap.add_argument("--preview", action="store_true", help="输出到 assets/_preview/，不动 demo/")
    args = ap.parse_args()

    if not Path(_CHROME).exists():
        print(f"[FAIL] 找不到 Chrome：{_CHROME}")
        return 1

    jobs = [j for j in JOBS if not args.only or j[0].startswith(args.only)]
    if not jobs:
        print("[FAIL] 没有匹配的渲染任务")
        return 1

    proc = launch()
    try:
        info = None
        for _ in range(40):
            try:
                info = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version"))
                break
            except Exception:
                time.sleep(0.25)
        if info is None:
            print("[FAIL] Chrome 调试端口没起来")
            return 1

        browser = CDP(info["webSocketDebuggerUrl"])
        for src, dest, w, h in jobs:
            svg = ASSETS / src
            if not svg.exists():
                print(f"[SKIP] 源不存在：{svg}")
                continue
            if args.preview or dest is None:
                out = ASSETS / "_preview" / (svg.stem + ".png")
            else:
                out = dest
            try:
                size = render(browser, svg, out, w, h)
            except Exception as exc:
                print(f"[FAIL] {src}：{type(exc).__name__}: {exc}")
                continue
            rel = out.relative_to(ROOT) if ROOT in out.parents else out
            print(f"[OK] {svg.name}  {w}×{h}  ->  {rel}  {round(size / 1024)} KB")
    finally:
        proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
