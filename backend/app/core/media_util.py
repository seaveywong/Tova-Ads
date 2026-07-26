"""媒体探测/抽帧工具（素材 AI 分析用）。

- 图片尺寸：Pillow（PIL）
- 视频时长：ffprobe
- 视频关键帧：ffmpeg 抽指定时间点的 JPG

工具缺失时优雅降级（返回 None/空），不阻断主流程——上传/分析仍可用，只是尺寸/帧拿不到。
"""
import os
import base64
import subprocess
import logging

logger = logging.getLogger("toveads.media")

# 视频扩展名（与 assets.py upload 的判定保持一致）
VIDEO_EXTS = (".mp4", ".mov", ".avi", ".webm", ".mkv")


def is_video(filepath: str) -> bool:
    return os.path.splitext(filepath)[1].lower() in VIDEO_EXTS


def image_dimensions(filepath: str) -> tuple[int, int] | None:
    """图片宽高 (w, h)；Pillow 没装或读不出 → None。"""
    try:
        from PIL import Image
        with Image.open(filepath) as im:
            return im.size  # (width, height)
    except Exception as e:
        logger.debug("image_dimensions 失败 %s: %s", filepath, e)
        return None


def video_duration(filepath: str) -> int | None:
    """视频时长（秒，整数）；ffprobe 没装 → None。"""
    if not _has("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", filepath],
            capture_output=True, text=True, timeout=20,
        )
        return int(float(out.stdout.strip() or 0)) or None
    except Exception as e:
        logger.debug("video_duration 失败 %s: %s", filepath, e)
        return None


def extract_keyframes(filepath: str, n: int = 3) -> list[bytes]:
    """抽视频关键帧（JPG 字节列表）。取 10%/50%/90% 时刻各一帧。

    ffmpeg 缺失或失败 → 返回空列表（调用方应回退提示"无法抽帧"）。
    """
    if not _has("ffmpeg"):
        return []
    dur = video_duration(filepath) or 0
    if dur <= 0:
        # 拿不到时长，按固定秒数抽前几帧
        marks = [1.0, 3.0, 5.0]
    else:
        marks = [max(0.5, dur * f) for f in (0.1, 0.5, 0.9)][:n]
    frames: list[bytes] = []
    for i, t in enumerate(marks):
        try:
            out = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}",
                 "-i", filepath, "-frames:v", "1", "-f", "image2", "-q:v", "3", "-an", "-"],
                capture_output=True, timeout=30,
            )
            if out.stdout:
                frames.append(out.stdout)
        except Exception as e:
            logger.debug("抽帧失败 t=%.2f %s: %s", t, filepath, e)
    return frames


def file_as_b64(filepath: str) -> str | None:
    """读文件 → base64 字符串（图片直接送视觉模型用）。"""
    try:
        with open(filepath, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except Exception as e:
        logger.debug("file_as_b64 失败 %s: %s", filepath, e)
        return None


def _has(tool: str) -> bool:
    """PATH 里有没有某可执行（ffmpeg/ffprobe）。"""
    from shutil import which
    return which(tool) is not None
