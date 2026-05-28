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
sudo install -m 644 "${ROOT}/deploy/systemd/taglens.target" /etc/systemd/system/
sudo systemctl daemon-reload
echo "已安装单元。启用并启动:"
echo "  sudo systemctl enable --now taglens.target"
echo "停止全部:"
echo "  sudo systemctl stop taglens.target"
echo "查看状态:"
echo "  systemctl status taglens.target taglens-backend.service taglens-frontend.service taglens-llm-gateway.service taglens-dtc-v1.service taglens-dtc-v2.service"
