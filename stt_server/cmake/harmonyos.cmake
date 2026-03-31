
# setup env for HarmonyOS cross compile
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/root/include)
link_directories(${CMAKE_CURRENT_SOURCE_DIR}/root/lib)

set(CROSS_HARMONYOS_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/root)

set(OPENSSL_INCLUDE_DIR ${CROSS_HARMONYOS_ROOT}/include)
set(OPENSSL_CRYPTO_LIBRARY ${CROSS_HARMONYOS_ROOT}/lib/libcrypto.so)
set(OPENSSL_SSL_LIBRARY ${CROSS_HARMONYOS_ROOT}/lib/libssl.so)

set(OPENBLAS_INCLUDE_DIRS ${CROSS_HARMONYOS_ROOT}/include)
set(OPENBLAS_LIBRARIES ${CROSS_HARMONYOS_ROOT}/lib/libopenblas.so)

find_package(PkgConfig REQUIRED)

# Use pkg-config to find all necessary FFmpeg modules
pkg_check_modules(LIBAV REQUIRED IMPORTED_TARGET 
    libavformat 
    libavcodec
    libswresample
    libavutil
)

# For cross-compilation: tell CMake to find OpenSSL in root/ before searching system paths.
# FindOpenSSL uses find_path/find_library, which search CMAKE_PREFIX_PATH.
list(PREPEND CMAKE_PREFIX_PATH ${CROSS_HARMONYOS_ROOT})

set(CPP_HTTPLIB_PROJECT "ext_cpp_httplib")
ExternalProject_Add(${CPP_HTTPLIB_PROJECT}
    PREFIX              ${EXTERNAL_ROOT}
    GIT_REPOSITORY      https://github.com/yhirose/cpp-httplib.git
    GIT_TAG             master
    SOURCE_DIR          ${EXTERNAL_ROOT}/cpp-httplib
    # 单头文件库：无需构建、无需安装
    CONFIGURE_COMMAND   ""
    BUILD_COMMAND       ""
    INSTALL_COMMAND     ""
    # 不更新（避免重复拉取）
    UPDATE_DISCONNECTED ON
)
# 获取 cpp-httplib 头文件路径
ExternalProject_Get_Property(${CPP_HTTPLIB_PROJECT} SOURCE_DIR)
set(CPP_HTTPLIB_INCLUDE_DIR ${SOURCE_DIR})


set(SENSE_VOICE_PROJECT "ext_sense_voice")
ExternalProject_Add(${SENSE_VOICE_PROJECT}
    PREFIX              ${EXTERNAL_ROOT}
    GIT_REPOSITORY      https://github.com/lovemefan/SenseVoice.cpp.git
    GIT_TAG             v1.4.0
    # 源码/构建目录
    SOURCE_DIR          ${EXTERNAL_ROOT}/sense-voice
    BINARY_DIR          ${EXTERNAL_ROOT}/sense-voice-build
    CMAKE_COMMAND       ${CMAKE_COMMAND}
    CMAKE_ARGS
        -DGGML_BLAS=ON
        -DGGML_BLAS_VENDOR=OpenBLAS
    CMAKE_CACHE_ARGS
        -DCMAKE_CXX_COMPILER:FILEPATH=${CMAKE_CXX_COMPILER}
        -DCMAKE_C_COMPILER:FILEPATH=${CMAKE_C_COMPILER}
        -DCMAKE_BUILD_TYPE:STRING=${CMAKE_BUILD_TYPE}
        -DCMAKE_CXX_FLAGS:STRING=${CMAKE_CXX_FLAGS}
        -DCMAKE_C_FLAGS:STRING=${CMAKE_C_FLAGS}
        -DCMAKE_CXX_STANDARD:STRING=${CMAKE_CXX_STANDARD}
        -DCMAKE_CXX_STANDARD_REQUIRED:BOOL=${CMAKE_CXX_STANDARD_REQUIRED}
        -DCMAKE_POSITION_INDEPENDENT_CODE:BOOL=${CMAKE_POSITION_INDEPENDENT_CODE}
        -DCMAKE_TOOLCHAIN_FILE:PATH=${CMAKE_TOOLCHAIN_FILE}
        -DCMAKE_INSTALL_PREFIX:PATH=${EXTERNAL_ROOT}/install
        -DSSRVODKA_APPEND_CMAKE_PREFIX_PATH:PATH=${SSRVODKA_APPEND_CMAKE_PREFIX_PATH}
        # FindBLAS uses find_library() which searches CMAKE_LIBRARY_PATH;
        # point it to our pre-built root/lib for cross-compilation
        -DCMAKE_LIBRARY_PATH:PATH=${CROSS_HARMONYOS_ROOT}/lib
        -DBLAS_LIBRARIES:FILEPATH=${OPENBLAS_LIBRARIES}
        -DBLAS_INCLUDE_DIRS:PATH=${OPENBLAS_INCLUDE_DIRS}
        # Also pass OpenSSL prefix so FindOpenSSL finds root/ first
        -DOPENSSL_INCLUDE_DIR:PATH=${OPENSSL_INCLUDE_DIR}
        -DOPENSSL_CRYPTO_LIBRARY:FILEPATH=${OPENSSL_CRYPTO_LIBRARY}
        -DOPENSSL_SSL_LIBRARY:FILEPATH=${OPENSSL_SSL_LIBRARY}
    # 不安装、不更新
    INSTALL_COMMAND     ""
    UPDATE_DISCONNECTED ON
)
# 获取 sense-voice 头文件路径 + 库文件路径
ExternalProject_Get_Property(${SENSE_VOICE_PROJECT} SOURCE_DIR BINARY_DIR)
set(SENSE_VOICE_SOURCE_DIR ${SOURCE_DIR})
set(SENSE_VOICE_LIB_DIR ${BINARY_DIR}/lib)


target_include_directories(${PROJECT_NAME} PRIVATE
    ${CPP_HTTPLIB_INCLUDE_DIR}
    ${SENSE_VOICE_SOURCE_DIR}/sense-voice/csrc
    ${SENSE_VOICE_SOURCE_DIR}/sense-voice/csrc/third-party/ggml/include
)

target_link_directories(${PROJECT_NAME} PRIVATE
    ${SENSE_VOICE_LIB_DIR}
    ${CROSS_HARMONYOS_ROOT}/lib
)
target_link_libraries(${PROJECT_NAME} PRIVATE
    avformat
    avcodec
    swresample
    avutil
)

add_dependencies(${PROJECT_NAME}
    ${CPP_HTTPLIB_PROJECT}
    ${SENSE_VOICE_PROJECT}
)

set_target_properties(${PROJECT_NAME} PROPERTIES
    BUILD_RPATH        "\$ORIGIN"
    INSTALL_RPATH      "\$ORIGIN"
    BUILD_WITH_INSTALL_RPATH TRUE
)

add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy
            ${SENSE_VOICE_LIB_DIR}/*.so
            ${CROSS_HARMONYOS_ROOT}/lib/*.so.*
            ${OHOS_SDK_NATIVE}/llvm/lib/${CMAKE_SYSTEM_PROCESSOR}-linux-ohos/libc++_shared.so
            ${OHOS_SDK_NATIVE}/llvm/lib/${CMAKE_SYSTEM_PROCESSOR}-linux-ohos/libomp.so
            ${PROJECT_BINARY_DIR}/
    COMMENT "Copying all .so files to binary directory..."
)