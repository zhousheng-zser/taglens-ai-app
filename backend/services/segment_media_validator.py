"""事件分段描述补齐前：用 ffmpeg 检测 MP4 是否损坏，损坏则不应送视觉模型。"""
from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

_PROBE_SECONDS = float(os.getenv("EVENT_SEGMENT_PLAYABLE_PROBE_SEC", "60"))
# 有效时长低于此值则跳过（默认 5s）
_MIN_DURATION_SEC = float(os.getenv("EVENT_SEGMENT_PLAYABLE_MIN_DURATION_SEC", "5"))
# ffmpeg 解码错误计数达到此值则跳过（默认 3；60s 探针下宏块错误常累计上千）
_MIN_DECODE_ERRORS_SKIP = int(os.getenv("EVENT_SEGMENT_PLAYABLE_MIN_DECODE_ERRORS", "10"))
_MIN_CORRUPT_FRAMES_SKIP = int(os.getenv("EVENT_SEGMENT_PLAYABLE_MIN_CORRUPT_FRAMES", "1"))
_DECODE_ERROR_PATTERNS = (
    r"corrupted macroblock",
    r"error while decoding MB",
    r"Decoding error",
    r"Decode error rate",
    r"Invalid NAL unit",
)
_VALIDATE_ENABLED = os.getenv("EVENT_SEGMENT_VALIDATE_PLAYABLE", "true").lower() in (
    "1",
    "true",
    "yes",
)


@dataclass
class VideoDamageReport:
    """单段视频的损坏检测结果（用于日志）。"""

    corrupted_macroblock: int = 0
    corrupt_frames: int = 0
    moov_at_end: bool = False
    browser_unplayable: bool = False
    first_frame_bad: bool = False
    duration_sec: float = 0.0
    size_mb: float = 0.0
    severity: str = "未检测"
    should_skip: bool = False
    skip_reason: Optional[str] = None

    def log_line(self) -> str:
        flags = []
        if self.moov_at_end:
            flags.append("moov在文件尾")
        if self.browser_unplayable:
            flags.append("浏览器难起播")
        if self.first_frame_bad:
            flags.append("首帧宏块异常")
        flag_text = f"，{','.join(flags)}" if flags else ""
        return (
            f"损坏程度={self.severity} | "
            f"解码错误×{self.corrupted_macroblock}，异常帧×{self.corrupt_frames}，"
            f"时长{self.duration_sec:.3f}s，体积{self.size_mb:.1f}MB{flag_text}"
        )


def is_playability_check_enabled() -> bool:
    return _VALIDATE_ENABLED and bool(
        shutil.which("ffprobe") and shutil.which("ffmpeg")
    )


def _moov_at_end(file_path: Path) -> bool:
    data = file_path.read_bytes()
    if len(data) < 32:
        return False
    pos = 0
    moov_pos: Optional[int] = None
    while pos + 8 <= len(data):
        size = int.from_bytes(data[pos : pos + 4], "big")
        atom_type = data[pos + 4 : pos + 8].decode("latin1", errors="replace")
        if atom_type == "moov":
            moov_pos = pos
        if size < 8:
            break
        pos += size
    if moov_pos is None:
        return False
    return moov_pos > len(data) * 0.85


def _head_ffprobe_fails(file_path: Path, head_bytes: int = 2 * 1024 * 1024) -> bool:
    """模拟浏览器边下边播：只读文件前部时 ffprobe 是否因缺少 moov 失败。"""
    size = file_path.stat().st_size
    if size < 32:
        return True
    # 小文件也测：只取前 25%（至少 64KB），moov 在尾部时此处应无索引
    read_len = min(head_bytes, max(64 * 1024, size // 4))
    if read_len >= size and _moov_at_end(file_path):
        read_len = max(32, size // 4)
    with file_path.open("rb") as fh:
        head = fh.read(min(read_len, size))
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=True) as tmp:
        tmp.write(head)
        tmp.flush()
        result = subprocess.run(
            ["ffprobe", "-v", "error", tmp.name],
            capture_output=True,
            text=True,
            timeout=15,
        )
    err = (result.stderr or "") + (result.stdout or "")
    return result.returncode != 0 and (
        "moov atom not found" in err or "Invalid data" in err
    )


def _probe_duration_sec(file_path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(file_path),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode != 0:
        return 0.0
    try:
        return float((result.stdout or "").strip() or 0)
    except ValueError:
        return 0.0


def _count_decode_errors(stderr: str) -> int:
    total = 0
    for pattern in _DECODE_ERROR_PATTERNS:
        total += len(re.findall(pattern, stderr))
    return total


def _decode_issue_counts(file_path: Path) -> Tuple[int, int]:
    cmd = [
        "ffmpeg",
        "-v",
        "warning",
        "-t",
        str(_PROBE_SECONDS),
        "-i",
        str(file_path),
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=max(90, int(_PROBE_SECONDS) + 30)
    )
    stderr = result.stderr or ""
    decode_errors = _count_decode_errors(stderr)
    corrupt_frames = stderr.count("corrupt decoded frame")
    return decode_errors, corrupt_frames


def _first_frame_decode_fails(file_path: Path) -> bool:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-err_detect",
            "explode",
            "-i",
            str(file_path),
            "-ss",
            "0",
            "-frames:v",
            "1",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    stderr = result.stderr or ""
    if result.returncode != 0:
        return True
    return _count_decode_errors(stderr) > 0 or "corrupt decoded frame" in stderr


def _classify_severity(
    decode_errors: int,
    corrupt_frames: int,
    moov_end: bool,
    head_fail: bool,
    first_bad: bool,
    duration_sec: float,
) -> Tuple[str, bool, Optional[str]]:
    """
    跳过规则（满足任一即不送 RLQ）：
    1. 有效时长 < _MIN_DURATION_SEC（默认 5s）
    2. 解码错误 ≥ _MIN_DECODE_ERRORS_SKIP（默认 3）
    3. 解码错误 ≥ 1 且（首帧失败 或 异常帧 ≥ _MIN_CORRUPT_FRAMES_SKIP）
    moov 在文件尾仅记日志，不单独触发跳过。
    """
    reasons: list[str] = []
    should_skip = False

    if duration_sec < _MIN_DURATION_SEC:
        reasons.append(
            f"有效时长过短（{duration_sec:.3f}s < {_MIN_DURATION_SEC}s），疑似截断或损坏"
        )
        should_skip = True

    if decode_errors >= _MIN_DECODE_ERRORS_SKIP:
        reasons.append(f"H.264 解码异常（解码错误×{decode_errors}）")
        should_skip = True
    elif decode_errors >= 1 and (
        first_bad or corrupt_frames >= _MIN_CORRUPT_FRAMES_SKIP
    ):
        detail = f"H.264 解码异常（解码错误×{decode_errors}，异常帧×{corrupt_frames}）"
        if first_bad:
            detail += "；首帧无法正常解码"
        reasons.append(detail)
        should_skip = True

    if should_skip and corrupt_frames >= 40 and decode_errors >= _MIN_DECODE_ERRORS_SKIP:
        reasons.append(f"解码异常帧过多（corrupt decoded frame×{corrupt_frames}）")

    if should_skip:
        return "严重（跳过）", True, "；".join(reasons)

    if decode_errors >= 2 or corrupt_frames >= 15:
        return "中等", False, None
    if decode_errors >= 1 or first_bad or moov_end or head_fail:
        return "轻微", False, None
    return "正常", False, None


def analyze_segment_video_file(file_path: Path) -> VideoDamageReport:
    if not file_path.is_file() or file_path.stat().st_size < 1024:
        return VideoDamageReport(
            severity="严重（跳过）",
            should_skip=True,
            skip_reason="视频文件过小或不存在",
        )

    if not is_playability_check_enabled():
        size_mb = file_path.stat().st_size / (1024 * 1024)
        return VideoDamageReport(
            severity="未检测",
            size_mb=round(size_mb, 2),
            should_skip=False,
        )

    decode_errors, corrupt_frames = _decode_issue_counts(file_path)
    moov_end = _moov_at_end(file_path)
    head_fail = _head_ffprobe_fails(file_path)
    first_bad = _first_frame_decode_fails(file_path)
    duration_sec = _probe_duration_sec(file_path)
    severity, should_skip, skip_reason = _classify_severity(
        decode_errors,
        corrupt_frames,
        moov_end,
        head_fail,
        first_bad,
        duration_sec,
    )

    return VideoDamageReport(
        corrupted_macroblock=decode_errors,
        corrupt_frames=corrupt_frames,
        moov_at_end=moov_end,
        browser_unplayable=head_fail,
        first_frame_bad=first_bad,
        duration_sec=duration_sec,
        size_mb=round(file_path.stat().st_size / (1024 * 1024), 2),
        severity=severity,
        should_skip=should_skip,
        skip_reason=skip_reason,
    )


def analyze_segment_video_bytes(video_bytes: bytes) -> VideoDamageReport:
    if not video_bytes:
        return VideoDamageReport(
            severity="严重（跳过）",
            should_skip=True,
            skip_reason="视频为空",
        )
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(video_bytes)
        tmp.flush()
        tmp_path = Path(tmp.name)
    try:
        return analyze_segment_video_file(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def check_segment_video_damaged(file_path: Path) -> Optional[str]:
    report = analyze_segment_video_file(file_path)
    return report.skip_reason


def check_segment_video_playable(file_path: Path) -> Optional[str]:
    return check_segment_video_damaged(file_path)
