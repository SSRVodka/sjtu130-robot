## How to build this product (native `x86_64`)?

1. install `libopenblas-dev` and `ffmpeg` (and dev);

2. execute `cmake -B <build-dir> && cmake --build <build-dir> -- -j`;

3. The binaries is under `<build-dir>` directory.


## How to build this product (`aarch64`)?

1. Put the pre-compiled HarmonyOS `root/` under `stt_server`;

2. execute [`ohos-build.sh`](../ohos-build.sh);

3. The binaries is under `build` directory.


> [!NOTE]
> 
> HarmonyOS `root/` can be built by [ohloha](https://gitcode.com/openharmony-robot/tools_ohloha);

