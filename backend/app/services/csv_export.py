"""通用 CSV 导出（报表下载）。

BOM UTF-8 前缀（Excel 双击打开不乱码）；列名走 i18n（按请求 locale）。
四处数据源：dashboard（账户汇总）/ads（广告级）/landing（子码级）/leads（潜客）。
"""
import csv
import io
from fastapi.responses import StreamingResponse


def build_csv(filename: str, headers: list[str], rows: list[list]) -> StreamingResponse:
    """headers/rows → CSV StreamingResponse。空单元格防 Excel 公式注入（= + - @ 开头加 '）。"""
    buf = io.StringIO()
    buf.write("﻿")  # BOM：Excel 识别 UTF-8
    w = csv.writer(buf)
    w.writerow(headers)

    def _safe(v):
        s = "" if v is None else str(v)
        if s[:1] in ("=", "+", "-", "@"):
            return "'" + s
        return s

    for r in rows:
        w.writerow([_safe(v) for v in r])
    buf.seek(0)
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}_{stamp}.csv"'},
    )
