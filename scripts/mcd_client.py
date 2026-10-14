"""麦当劳中国 MCP 客户端封装（Streamable HTTP）。

用途：把 MCP 的 JSON-RPC 调用包装成 Python 函数，供替换方案枚举与计价使用。

鉴权（三选一，优先级从高到低）：
    1. 显式传入 McdClient(token="...")
    2. 环境变量 MCD_MCP_TOKEN
    3. ~/.workbuddy/mcp.json 里 mcd-mcp.headers.Authorization

注意：
    - calculate-price 返回的金额单位是「分」
    - order-list 的 realTotalAmount 是字符串型的「元」
    两者方向相反，切勿混用。详见 references/mcp-pitfalls.md
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_URL = "https://mcp.mcd.cn"

# 这些值视为「还没填」，不要当作真实 Token
PLACEHOLDER_TOKENS = {"", "YOUR_MCP_TOKEN", "PASTE_YOUR_TOKEN", "xxx", "TODO"}

_JSONRPC_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


class McpError(RuntimeError):
    """MCP 调用失败。"""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


def load_token_from_config(path: str | Path | None = None) -> str | None:
    """从 WorkBuddy 的 mcp.json 里读取 mcd-mcp 的 Token。

    默认路径：~/.workbuddy/mcp.json（Windows 即 C:\\Users\\<你>\\.workbuddy\\mcp.json）
    这样只需在配置文件里填一次，脚本与会话可共用同一个 Token。

    注意：用 utf-8-sig 读取，以兼容 Windows PowerShell 写入时可能带的 BOM。
    """
    config_path = Path(path) if path else Path.home() / ".workbuddy" / "mcp.json"
    if not config_path.exists():
        return None
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None

    server = (cfg.get("mcpServers") or {}).get("mcd-mcp") or {}
    auth = str((server.get("headers") or {}).get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        auth = auth[7:].strip()
    if auth in PLACEHOLDER_TOKENS:
        return None
    return auth or None


def cents_to_yuan(value: Any) -> float:
    """把「分」转换为「元」。无法解析时抛错，绝不猜测。"""
    if value is None:
        raise McpError("金额字段缺失，拒绝猜测价格")
    return round(int(value) / 100, 2)


class McdClient:
    """麦当劳 MCP 的最小可用客户端。"""

    def __init__(
        self,
        token: str | None = None,
        url: str | None = None,
        timeout: int = 30,
        config_path: str | Path | None = None,
    ):
        # 优先级：显式传参 > 环境变量 > ~/.workbuddy/mcp.json
        self.token = token or os.environ.get("MCD_MCP_TOKEN") or load_token_from_config(config_path)
        if not self.token:
            raise McpError(
                "缺少 MCP Token。三选一：\n"
                "  1. 在 ~/.workbuddy/mcp.json 的 mcd-mcp.headers.Authorization 里填好\n"
                "  2. 设置环境变量 MCD_MCP_TOKEN\n"
                "  3. 通过 --token 传入\n"
                "申请地址：https://mcp.mcd.cn （手机号登录 → 控制台 → 激活）"
            )
        self.url = (url or DEFAULT_URL).rstrip("/")
        self.timeout = timeout
        self._session_id: str | None = None
        self._request_id = 0

    # ---- 公开接口 ----

    def call(self, tool: str, **params: Any) -> Any:
        """调用一个 MCP 工具，返回业务数据（成功时剥掉信封取 data）。"""
        result = self._result("tools/call", {"name": tool, "arguments": params}, label=tool)
        payload = self._unwrap(result)
        if isinstance(payload, dict) and "success" in payload:
            if payload.get("success") is False:
                raise McpError(
                    f"{tool} 业务失败: [{payload.get('code')}] {payload.get('message')}"
                )
            data = payload.get("data")
            return data if data is not None else payload
        return payload

    def list_tools(self) -> list[dict[str, Any]]:
        """列出服务端可用工具。"""
        result = self._result("tools/list", {}, label="tools/list")
        items = result.get("tools") if isinstance(result, dict) else result
        return items or []

    # ---- JSON-RPC 内部实现 ----

    def _result(self, method: str, params: dict[str, Any], label: str = "") -> dict[str, Any]:
        """发起一次 JSON-RPC 调用，返回 result 字段（含错误处理）。"""
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        raw = self._post(payload)
        if "error" in raw:
            err = raw["error"]
            raise McpError(
                f"{label or method} 调用失败: {err.get('message')}", code=err.get("code")
            )
        result = raw.get("result", {})
        if result.get("isError"):
            detail = (result.get("content") or [{}])[0].get("text", "未知错误")
            raise McpError(f"{label or method} 返回错误: {detail}")
        return result

    @staticmethod
    def _unwrap(result: dict[str, Any]) -> dict[str, Any]:
        """把 MCP content 数组还原成 dict。"""
        content = result.get("content") or []
        if not content:
            return result.get("structuredContent") or {}
        first = content[0]
        text = first.get("text")
        if not text:
            return result.get("structuredContent") or first
        return _parse_text_payload(text)

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        headers = dict(_JSONRPC_HEADERS)
        headers["Authorization"] = f"Bearer {self.token}"
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        # 麦当劳 MCP 的端点就是配置里的 url 本身，不要再拼接 /mcp（会 404）
        req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                session = resp.headers.get("Mcp-Session-Id")
                if session:
                    self._session_id = session
                ctype = (resp.headers.get("Content-Type") or "").lower()
                raw_body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:  # 401 / 429 等
            raise McpError(f"HTTP {exc.code}: {exc.reason}", code=exc.code) from exc
        except urllib.error.URLError as exc:
            raise McpError(f"网络不可达: {exc.reason}") from exc

        if "text/event-stream" in ctype:
            return self._parse_sse(raw_body)
        if raw_body.strip():
            return json.loads(raw_body)
        return {}

    @staticmethod
    def _parse_sse(body: str) -> dict[str, Any]:
        """从 SSE 流里取出最后一个 JSON-RPC 响应。"""
        last: dict[str, Any] = {}
        for line in body.splitlines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                last = json.loads(data)
            except json.JSONDecodeError:
                continue
        return last

    # ---- 常用业务方法（参数是硬约束，见 references/mcp-pitfalls.md）----

    def nearby_stores(self, be_type: int, search_type: int, **kw: Any) -> dict[str, Any]:
        """查询附近门店。beType 与 searchType 必传。"""
        return self.call("query-nearby-stores", beType=be_type, searchType=search_type, **kw)

    def meals(self, store_code: str, order_type: int, be_type: int) -> dict[str, Any]:
        return self.call(
            "query-meals", storeCode=store_code, orderType=order_type, beType=be_type
        )

    def meal_detail(
        self, store_code: str, order_type: int, be_type: int, code: str
    ) -> dict[str, Any]:
        return self.call(
            "query-meal-detail",
            storeCode=store_code,
            orderType=order_type,
            beType=be_type,
            code=code,
        )

    def calculate_price(self, **kw: Any) -> dict[str, Any]:
        """计价。商品字段必须是 items: [{productCode, quantity}]。"""
        return self.call("calculate-price", **kw)


# ---- 响应解析（模块级）----


def _parse_text_payload(text: str) -> dict[str, Any]:
    """解析服务端返回的文本载荷，还原出业务响应对象。

    麦当劳 MCP 的返回形态不固定，至少见过三种：
      1. 纯 JSON
      2. 「## Original Response + JSON」的混合文本
      3. 「字段说明 + 内嵌 JSON + 补充说明」的混合文本

    统一提取出内嵌的业务响应（保留 success / code / message / data），
    由 McdClient.call() 负责判断业务成败并剥信封。
    不要把一整段散文当成业务结果。
    """
    stripped = text.strip()

    # 形态 1：整体就是 JSON
    obj = _try_json_object(stripped)
    if obj is not None:
        return obj

    # 形态 2/3：从混合文本中提取内嵌 JSON
    obj = _extract_embedded_json(text)
    if obj is not None:
        return obj

    return {"text": text}


def _try_json_object(raw: str) -> dict[str, Any] | None:
    """整体解析 JSON 对象，失败返回 None。"""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_embedded_json(text: str) -> dict[str, Any] | None:
    """从说明文字中扫描出内嵌的 JSON 对象。

    用 raw_decode 从每个 `{` 位置尝试解析，
    只接受含 success / data 字段的对象，避免误抓说明里的花括号。
    """
    decoder = json.JSONDecoder()
    idx = 0
    while True:
        pos = text.find("{", idx)
        if pos < 0:
            return None
        try:
            obj, end = decoder.raw_decode(text, pos)
        except (json.JSONDecodeError, ValueError):
            idx = pos + 1
            continue
        if isinstance(obj, dict) and ("success" in obj or "data" in obj):
            return obj
        idx = max(end, pos + 1)
