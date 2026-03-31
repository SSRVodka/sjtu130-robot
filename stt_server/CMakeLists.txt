# ─────────────────────────────────────────────────────────────────────────────
# sense-voice-server — OpenAI-compatible STT HTTP server
# ─────────────────────────────────────────────────────────────────────────────

cmake_minimum_required(VERSION 3.24)
project(stt-server)

include(ExternalProject)
find_package(Threads REQUIRED)

set(EXTERNAL_ROOT ${PROJECT_BINARY_DIR}/external)


add_executable(${PROJECT_NAME}
    server.cc
)

if (OHOS)
    include(cmake/harmonyos.cmake)
else()
    include(cmake/linux.cmake)
endif()

target_link_libraries(${PROJECT_NAME} PRIVATE
    common
    sense-voice-core
    ggml ggml-base ggml-blas ggml-cpu
    Threads::Threads
)


find_package(OpenSSL QUIET)
if(OpenSSL_FOUND)
    target_compile_definitions(${PROJECT_NAME} PRIVATE CPPHTTPLIB_OPENSSL_SUPPORT)
    target_link_libraries(${PROJECT_NAME} PRIVATE OpenSSL::SSL OpenSSL::Crypto)
else()
    message(WARNING "OpenSSL not found for ${PROJECT_NAME}")
endif()

target_compile_features(${PROJECT_NAME} PRIVATE cxx_std_17)
