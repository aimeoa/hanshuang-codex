#!/bin/bash
# 寒霜破甲工具 - 一键部署脚本 (Linux Ubuntu/Debian)
echo '=== 安装依赖 ==='
apt update -y
apt install -y python3 python3-pip python3-venv
echo '=== 创建虚拟环境 ==='
cd /opt
python3 -m venv hanshuang
cd hanshuang
source bin/activate
echo '=== 安装 Python 包 ==='
pip install fastapi uvicorn python-multipart
echo '=== 复制代码 ==='
mkdir -p /opt/hanshuang/app
cp main.py /opt/hanshuang/app/
cp requirements.txt /opt/hanshuang/app/
cd /opt/hanshuang/app
echo '=== 启动服务 ==='
nohup uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2 > /var/log/hanshuang.log 2>&1 &
echo '=== 部署完成 ==='
echo 'API 地址: http://<你的服务器IP>:8000'
echo 'API 文档: http://<你的服务器IP>:8000/docs'
