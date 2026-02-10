#!/bin/zsh

DATA_DIR="$(cd "$(dirname "$0")" && pwd)"

docker run --pull=always \
  --restart=unless-stopped \
  -d \
  -p 5006:5006 \
  -v "${DATA_DIR}:/data" \
  --name actual \
  actualbudget/actual-server:latest
