#!/bin/bash

CROSS_HARMONYOS_ROOT=$PWD/root

cmake -B build \
    -DCMAKE_TOOLCHAIN_FILE=$PWD/ohos.toolchain.xhw.cmake \
    -DCMAKE_BUILD_TYPE=Release

cmake --build build -- -j
