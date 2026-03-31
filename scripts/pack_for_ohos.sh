#!/bin/bash

REPO_ROOT=$(dirname $(dirname $(realpath $0)))

cd $REPO_ROOT

mkdir -p _deploy

cp -r agent/ museum_tour/ scripts/ _deploy/
mkdir -p _deploy/stt_server/bin/aarch64 _deploy/stt_server/models
cp -r stt_server/bin/aarch64/* _deploy/stt_server/bin/aarch64/
cp -r stt_server/models/* _deploy/stt_server/models/

tar -zcvf ohos-deploy-$(date +%Y%m%d%H%M%S).tar.gz -C _deploy/ .

rm -rf _deploy/
