#!/bin/zsh

docker pull actualbudget/actual-server:latest
docker stop actual
docker rm actual
docker run --pull=always --restart=unless-stopped -d -p 5006:5006 \
  -v ~/docker/actual-data:/data --name actual actualbudget/actual-server:latest
