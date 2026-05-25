#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
torchrun 入口：仅 RANK=0 启动 uvicorn，其它 rank 占位（保持进程组存活）。
由 start_sam3_server.sh 通过 torch.distributed.run 调用。
"""
from __future__ import annotations

import os
import time


def main() -> None:
    rank = int(os.environ.get("RANK", "0"))
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))

    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.set_device(local_rank)
            print(
                f"[SAM3 launcher] rank={rank} local_rank={local_rank} "
                f"device=cuda:{local_rank} ({torch.cuda.get_device_name(local_rank)})"
            )
    except Exception as exc:
        print(f"[SAM3 launcher] rank={rank} CUDA init warning: {exc}")

    if rank != 0:
        print(f"[SAM3 launcher] rank={rank} standby (HTTP 仅由 rank 0 提供)")
        while True:
            time.sleep(3600)
        return

    import uvicorn

    app_module = os.environ.get("UVICORN_APP", "sam3_server:app")
    port = int(os.environ.get("SAM3_SERVER_PORT", "8011"))
    host = os.environ.get("SERVER_HOST", "0.0.0.0")
    print(f"[SAM3 launcher] rank=0 启动 uvicorn {app_module} @ {host}:{port}")
    uvicorn.run(app_module, host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
