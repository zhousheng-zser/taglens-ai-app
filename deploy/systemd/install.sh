#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ "${ROOT}" != "/opt/Traffic-LLM/zser/taglens-ai-app" ]]; then
  echo "警告: 当前仓库路径为 ${ROOT}，单元文件内写死了 /opt/Traffic-LLM/zser/taglens-ai-app，请先改 .service 再安装。" >&2
fi
sudo install -m 644 "${ROOT}/deploy/systemd/taglens-backend.service" /etc/systemd/system/
sudo install -m 644 "${ROOT}/deploy/systemd/taglens-frontend.service" /etc/systemd/system/
sudo install -m 644 "${ROOT}/deploy/systemd/taglens-llm-gateway.service" /etc/systemd/system/
sudo install -m 644 "${ROOT}/deploy/systemd/taglens-dtc-v1.service" /etc/systemd/system/
sudo install -m 644 "${ROOT}/deploy/systemd/taglens-dtc-v2.service" /etc/systemd/system/
sudo install -m 644 "${ROOT}/deploy/systemd/taglens-sync-01.service" /etc/systemd/system/
sudo install -m 644 "${ROOT}/deploy/systemd/taglens-sync-02.service" /etc/systemd/system/
sudo install -m 644 "${ROOT}/deploy/systemd/taglens-sync-03.service" /etc/systemd/system/
sudo install -m 644 "${ROOT}/deploy/systemd/taglens-sync-04.service" /etc/systemd/system/
sudo install -m 644 "${ROOT}/deploy/systemd/taglens.target" /etc/systemd/system/
sudo systemctl daemon-reload
echo "已安装单元。启用并启动核心栈:"
echo "  sudo systemctl enable --now taglens.target"
echo "停止核心栈 (不会停止独立 sync 单元):"
echo "  sudo systemctl stop taglens.target"
echo "项目同步 (默认不开机自启，由 UI 或手动 systemctl start):"
echo "  sudo systemctl start taglens-sync-03.service"
echo "  sudo systemctl stop taglens-sync-03.service"
echo "  tail -f ${ROOT}/logs/sync_task_03.py.log"
echo "查看状态:"
echo "  systemctl status taglens.target taglens-backend.service taglens-frontend.service taglens-llm-gateway.service taglens-dtc-v1.service taglens-dtc-v2.service"
echo "  systemctl status taglens-sync-01.service taglens-sync-02.service taglens-sync-03.service taglens-sync-04.service"
