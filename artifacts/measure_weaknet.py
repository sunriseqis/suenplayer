#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B3 弱网量化：离线下载 mp4 的 moov 位置对“首帧前元数据就绪时间”与 seek 响应的影响。

方法（网络层代理指标，非浏览器真实解码首帧）：
1. ffmpeg 生成同内容两份 mp4：tail-moov（默认）与 faststart（moov 在头部）。
2. 本地起一个“弱网代理”文件服务器：每个请求固定 200ms 延迟，限速 2 Mbps（256 KB/s）。
3. 模拟浏览器 progressive 播放行为：先 Range 取头部 64KB 检查是否含 moov；
   不含则按 mp4 atom 结构定位 moov 的偏移，再 Range 取该 atom（尾部）。
   记录“元数据就绪”所需的时间与传输字节。
4. seek 测试：Range 取文件 50% 处 256KB 的完成时间（两边机制相同，作对照）。
结论：moov 在尾部时必须先拉头部块再跳到文件尾取 moov（多 1 RTT + 长距离传输），
     弱网下元数据就绪时间显著恶化；faststart 后一次头部读取即可就绪。
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LATENCY_S = 0.2            # 每请求固定延迟 200ms
RATE_BPS = 2 * 1024 * 1024 # 2 Mbps
CHUNK_HEAD = 64 * 1024     # 浏览器首块探测大小
SEEK_OFF_FRAC = 0.5
SEEK_LEN = 256 * 1024


def mp4_top_atoms(fp):
    size = os.path.getsize(fp)
    out, pos = [], 0
    with open(fp, "rb") as f:
        while pos < size:
            f.seek(pos)
            hdr = f.read(16)
            if len(hdr) < 8:
                break
            n = struct.unpack(">I", hdr[:4])[0]
            typ = hdr[4:8]
            if n == 1:
                n = struct.unpack(">Q", hdr[8:16])[0]
            if n == 0:
                n = size - pos
            out.append((pos, n, typ))
            pos += n
    return out


def make_sample(tmp, dur=30, w=640, h=360, fps=24):
    """生成尾部 moov 与头部 moov 两份同内容 mp4。"""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    tail = tmp / "sample_tail.mp4"
    head = tmp / "sample_head.mp4"
    vf = f"testsrc2=duration={dur}:size={w}x{h}:rate={fps}"
    af = f"sine=frequency=440:duration={dur}"
    r = subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", vf,
         "-f", "lavfi", "-i", af, "-c:v", "libx264", "-preset", "veryfast",
         "-pix_fmt", "yuv420p", "-c:a", "aac", str(tail)],
        capture_output=True, timeout=180)
    if r.returncode != 0 or not tail.exists():
        print("ffmpeg 生成失败:", r.stderr[-300:], file=sys.stderr)
        return None
    r2 = subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(tail),
         "-c", "copy", "-movflags", "+faststart", str(head)],
        capture_output=True, timeout=180)
    if r2.returncode != 0 or not head.exists():
        print("faststart 转封装失败:", r2.stderr[-300:], file=sys.stderr)
        return None
    return tail, head


class WeakNetHandler(BaseHTTPRequestHandler):
    """限速 + 固定延迟的静态文件服务（支持 Range）。"""
    file_path = None
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _throttled_send(self, data):
        # 按速率分块发送，模拟 2Mbps 带宽
        chunk_size = 32 * 1024
        per_chunk_delay = chunk_size / (RATE_BPS / 8)
        time.sleep(LATENCY_S)
        view = memoryview(data)
        for i in range(0, len(view), chunk_size):
            self.wfile.write(view[i:i + chunk_size])
            if i + chunk_size < len(view):
                time.sleep(per_chunk_delay)

    def do_GET(self):
        data = self.file_path.read_bytes()
        rng = self.headers.get("Range")
        status, payload, cr = 200, data, None
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng.strip())
            if m:
                total = len(data)
                start = int(m.group(1)) if m.group(1) else None
                end = int(m.group(2)) if m.group(2) else total - 1
                if start is None:
                    start = max(0, total - int(m.group(2) or 0))
                    end = total - 1
                if start >= total or start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{total}")
                    self.end_headers()
                    return
                end = min(end, total - 1)
                status, payload = 206, data[start:end + 1]
                cr = f"bytes {start}-{end}/{total}"
        self.send_response(status)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(payload)))
        if cr:
            self.send_header("Content-Range", cr)
        self.end_headers()
        self._throttled_send(payload)


def serve(fp):
    WeakNetHandler.file_path = fp
    srv = ThreadingHTTPServer(("127.0.0.1", 0), WeakNetHandler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def probe_metadata_ready(port, fp):
    """模拟播放器：头部 64KB 找 moov；找不到则解析 atom 跳到 moov 偏移再取。
    返回 (耗时秒, 传输字节, 请求数)。"""
    import httpx
    total = fp.stat().st_size
    t0 = time.time()
    transferred = 0
    reqs = 0
    with httpx.Client(timeout=120) as c:
        url = f"http://127.0.0.1:{port}/video.mp4"
        # 第一块：头部
        r = c.get(url, headers={"Range": f"bytes=0-{CHUNK_HEAD - 1}"})
        reqs += 1
        transferred += len(r.content)
        atoms = mp4_top_atoms(fp)
        moov = next((a for a in atoms if a[2] == b"moov"), None)
        if moov and moov[0] >= CHUNK_HEAD:
            # moov 不在头部：播放器需再次请求尾部
            pos, length, _ = moov
            r2 = c.get(url, headers={"Range": f"bytes={pos}-{pos + length - 1}"})
            reqs += 1
            transferred += len(r2.content)
        elif moov is None:
            raise RuntimeError("无 moov atom")
    return time.time() - t0, transferred, reqs


def probe_seek(port, fp):
    """seek 到 50% 处取 256KB 的完成时间（含固定延迟与限速）。"""
    import httpx
    total = fp.stat().st_size
    start = int(total * SEEK_OFF_FRAC)
    end = start + SEEK_LEN - 1
    t0 = time.time()
    with httpx.Client(timeout=120) as c:
        r = c.get(f"http://127.0.0.1:{port}/video.mp4",
                  headers={"Range": f"bytes={start}-{end}"})
        ok = r.status_code == 206 and len(r.content) == SEEK_LEN
    return time.time() - t0, ok


def main():
    tmp = Path(os.environ.get("B3_TMP") or "/tmp/b3_weaknet")
    tmp.mkdir(parents=True, exist_ok=True)
    made = make_sample(tmp)
    result = {"rate_mbps": RATE_BPS / 1024 / 1024, "latency_ms": LATENCY_S * 1000}
    if not made:
        result["error"] = "ffmpeg 不可用，无法生成样本"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    tail, head = made
    result["file_bytes"] = tail.stat().st_size
    for name, fp in (("tail_moov", tail), ("faststart", head)):
        srv, port = serve(fp)
        try:
            t_meta, b_meta, reqs = probe_metadata_ready(port, fp)
            t_seek, ok = probe_seek(port, fp)
            result[name] = {
                "metadata_ready_s": round(t_meta, 2),
                "metadata_bytes": b_meta,
                "metadata_requests": reqs,
                "seek_50pct_256k_s": round(t_seek, 2),
                "seek_ok": ok,
            }
        finally:
            srv.shutdown()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    (Path(__file__).parent / "b3_weaknet_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
