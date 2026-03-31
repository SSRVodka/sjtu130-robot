//
// server.cc — OpenAI-compatible Speech-to-Text HTTP server backed by SenseVoice.cpp
//
// Endpoint : POST /v1/audio/transcriptions  (multipart/form-data)
// Fields   : file (required), language, response_format (json|text), stream (true|false)
// Health   : GET  /health
//
// Build (add to examples/server/ in the SenseVoice.cpp tree and update CMakeLists):
//   Requires httplib.h  →  https://github.com/yhirose/cpp-httplib  (single-header, v0.14+)
//   Place httplib.h in the same directory as this file.
//
// Example usage:
//   ./sense-voice-server -m models/ggml-small.bin -p 8080
//
//   curl http://localhost:8080/v1/audio/transcriptions
//        -F file=@audio.wav -F language=zh -F response_format=json
//
//   curl http://localhost:8080/v1/audio/transcriptions
//        -F file=@audio.wav -F stream=true        (Server-Sent Events)
//

#include "common.h"
#include "sense-voice.h"

#include "httplib.h"   // cpp-httplib — single header, no other HTTP dependency needed

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <unistd.h>
#include <vector>

// ─────────────────────────────────────────────────────────────────────────────
// Global model context — loaded once at startup, never freed until exit
// ─────────────────────────────────────────────────────────────────────────────

static sense_voice_context *g_ctx = nullptr;
static std::mutex            g_mtx;  // inference is single-threaded per context

struct ServerParams {
    std::string model      = "models/ggml-small.bin";
    std::string host       = "0.0.0.0";
    int         port       = 8080;
    int         n_threads  = std::min(4, (int)std::thread::hardware_concurrency());
    std::string language   = "auto";
    bool        use_gpu    = true;
    bool        flash_attn = false;
    bool        use_itn    = false;
    bool        use_prefix = false;  // when true, emit <lang><emotion> prefix tokens
};

// ─────────────────────────────────────────────────────────────────────────────
// Context cleanup  (mirrors main.cc / stream.cc — not exported by the library)
// ─────────────────────────────────────────────────────────────────────────────

static void sv_free(sense_voice_context *ctx) {
    if (!ctx) return;
    if (ctx->state) {
        if (ctx->state->vad_ctx)                    ggml_free(ctx->state->vad_ctx);
        if (ctx->state->vad_lstm_hidden_state_buffer)
            ggml_backend_buffer_free(ctx->state->vad_lstm_hidden_state_buffer);
        if (ctx->state->vad_lstm_context_buffer)
            ggml_backend_buffer_free(ctx->state->vad_lstm_context_buffer);
    }
    sense_voice_free_state(ctx->state);
    ggml_backend_buffer_free(ctx->model.buffer);
    ggml_free(ctx->model.ctx);
    delete ctx;
}

// ─────────────────────────────────────────────────────────────────────────────
// Minimal JSON helpers (avoids an external JSON library)
// ─────────────────────────────────────────────────────────────────────────────

static std::string json_escape(const std::string &s) {
    std::string o;
    o.reserve(s.size());
    for (unsigned char c : s) {
        switch (c) {
            case '"':  o += "\\\""; break;
            case '\\': o += "\\\\"; break;
            case '\n': o += "\\n";  break;
            case '\r': o += "\\r";  break;
            case '\t': o += "\\t";  break;
            default:
                if (c < 0x20) {
                    char b[8]; snprintf(b, sizeof(b), "\\u%04x", c); o += b;
                } else {
                    o += (char)c;
                }
        }
    }
    return o;
}

static std::string json_ok(const std::string &text) {
    return R"({"text":")" + json_escape(text) + "\"}";
}
static std::string json_err(const std::string &msg) {
    return R"({"error":{"message":")" + json_escape(msg)
         + R"(","type":"invalid_request_error"}})";
}

// ─────────────────────────────────────────────────────────────────────────────
// Audio decoding  — WAV (native) + ffmpeg fallback for other formats
// ─────────────────────────────────────────────────────────────────────────────

static uint16_t u16le(const void *p) { uint16_t v; memcpy(&v, p, 2); return v; }
static uint32_t u32le(const void *p) { uint32_t v; memcpy(&v, p, 4); return v; }

// Linear interpolation resampler — adequate quality for speech recognition
static std::vector<float> resample(const std::vector<float> &src,
                                    int src_rate, int dst_rate) {
    if (src_rate == dst_rate || src.empty()) return src;
    size_t n = (size_t)((double)src.size() * dst_rate / src_rate + 0.5);
    std::vector<float> dst(n);
    double ratio = (double)(src.size() - 1) / std::max((double)(n - 1), 1.0);
    for (size_t i = 0; i < n; ++i) {
        double p  = i * ratio;
        size_t lo = (size_t)p,  hi = std::min(lo + 1, src.size() - 1);
        float  f  = (float)(p - (double)lo);
        dst[i]    = src[lo] * (1.0f - f) + src[hi] * f;
    }
    return dst;
}

// Parse a PCM WAV file (int16 or float32, any channel count, any sample rate).
// Returns mono float samples resampled to SENSE_VOICE_SAMPLE_RATE, or {} on error.
static std::vector<float> decode_wav(const std::vector<char> &buf) {
    const uint8_t *p = (const uint8_t *)buf.data();
    size_t          n = buf.size();

    if (n < 44) return {};
    if (memcmp(p, "RIFF", 4) != 0 || memcmp(p + 8, "WAVE", 4) != 0) return {};

    uint16_t        audio_fmt = 0, channels = 0, bits = 0;
    uint32_t        sample_rate = 0;
    const uint8_t  *pcm_ptr  = nullptr;
    size_t          pcm_bytes = 0;

    for (size_t off = 12; off + 8 <= n; ) {
        uint32_t csize = u32le(p + off + 4);
        if (memcmp(p + off, "fmt ", 4) == 0 && csize >= 16) {
            audio_fmt   = u16le(p + off + 8);
            channels    = u16le(p + off + 10);
            sample_rate = u32le(p + off + 12);
            bits        = u16le(p + off + 22);
        } else if (memcmp(p + off, "data", 4) == 0) {
            pcm_ptr   = p + off + 8;
            pcm_bytes = std::min((size_t)csize, n - (off + 8));
        }
        off += 8 + csize;
        if (off & 1) ++off;  // RIFF chunk word-align
    }

    // audio_fmt 1 = PCM int, 3 = IEEE float
    if (!pcm_ptr || channels == 0) return {};
    if (audio_fmt != 1 && audio_fmt != 3) return {};
    if (bits != 16 && bits != 32) return {};

    size_t bps     = bits / 8;
    size_t n_frames = pcm_bytes / (bps * channels);

    std::vector<float> mono(n_frames);
    for (size_t i = 0; i < n_frames; ++i) {
        float sum = 0.0f;
        for (int c = 0; c < (int)channels; ++c) {
            const void *sp = pcm_ptr + (i * channels + c) * bps;
            float v = 0.0f;
            if (audio_fmt == 1 && bits == 16) {
                int16_t s; memcpy(&s, sp, 2); v = s / 32768.0f;
            } else if (audio_fmt == 1 && bits == 32) {
                int32_t s; memcpy(&s, sp, 4); v = s / 2147483648.0f;
            } else {
                memcpy(&v, sp, 4);  // float32 PCM
            }
            sum += v;
        }
        mono[i] = sum / (float)channels;
    }

    return resample(mono, (int)sample_rate, SENSE_VOICE_SAMPLE_RATE);
}

// Convert any audio format to a canonical WAV via ffmpeg, then decode it.
// Returns {} if ffmpeg is not available or conversion fails.
static std::vector<float> decode_via_ffmpeg(const std::vector<char> &data) {
    // Write uploaded bytes to a temporary file
    char in_path[64];
    snprintf(in_path, sizeof(in_path), "/tmp/sv_in_%d_XXXXXX", (int)getpid());
    int fd = mkstemp(in_path);
    if (fd < 0) return {};
    bool ok = (write(fd, data.data(), data.size()) == (ssize_t)data.size());
    close(fd);
    if (!ok) { unlink(in_path); return {}; }

    // Output temp WAV path
    char out_path[80];
    snprintf(out_path, sizeof(out_path), "%s.wav", in_path);

    char cmd[512];
    snprintf(cmd, sizeof(cmd),
        "ffmpeg -y -i '%s' -ac 1 -ar %d -sample_fmt s16 '%s' >/dev/null 2>&1",
        in_path, SENSE_VOICE_SAMPLE_RATE, out_path);
    int rc = system(cmd);
    unlink(in_path);
    if (rc != 0) { unlink(out_path); return {}; }

    FILE *f = fopen(out_path, "rb");
    if (!f) { unlink(out_path); return {}; }
    fseek(f, 0, SEEK_END); long sz = ftell(f); rewind(f);
    std::vector<char> wav(sz);
    fread(wav.data(), 1, sz, f);
    fclose(f);
    unlink(out_path);

    return decode_wav(wav);  // already at SENSE_VOICE_SAMPLE_RATE
}

// Entry: try native WAV parser first, then ffmpeg for mp3/m4a/ogg/flac/webm/…
static std::vector<float> decode_audio(const std::vector<char> &data) {
    auto pcm = decode_wav(data);
    if (!pcm.empty()) return pcm;
    return decode_via_ffmpeg(data);
}

// ─────────────────────────────────────────────────────────────────────────────
// Transcription
// ─────────────────────────────────────────────────────────────────────────────

// Redirect stdout to a pipe, call fn(), return everything that was printed.
// This lets us capture sense_voice_print_output() without modifying the library.
static std::string capture_stdout(const std::function<void()> &fn) {
    int pfd[2];
    if (pipe(pfd) != 0) return "";

    fflush(stdout);
    int saved = dup(STDOUT_FILENO);
    dup2(pfd[1], STDOUT_FILENO);
    close(pfd[1]);

    fn();
    fflush(stdout);

    dup2(saved, STDOUT_FILENO);
    close(saved);

    fcntl(pfd[0], F_SETFL, O_NONBLOCK);
    std::string out;
    char buf[4096];
    for (ssize_t nr; (nr = read(pfd[0], buf, sizeof(buf))) > 0; )
        out.append(buf, nr);
    close(pfd[0]);

    // Strip trailing whitespace / newlines
    while (!out.empty() &&
           (out.back() == '\n' || out.back() == '\r' || out.back() == ' '))
        out.pop_back();
    return out;
}

// Run inference and return the transcribed text.
// MUST be called with g_mtx held.
static std::string run_inference(const std::vector<float> &pcm,
                                  const std::string        &lang,
                                  const ServerParams       &sp) {
    // sense_voice_full_parallel expects double samples
    std::vector<double> samples(pcm.begin(), pcm.end());

    sense_voice_full_params wp = sense_voice_full_default_params(SENSE_VOICE_SAMPLING_GREEDY);
    wp.language   = lang.empty() ? sp.language.c_str() : lang.c_str();
    wp.n_threads  = sp.n_threads;
    wp.debug_mode = false;

    g_ctx->language_id = sense_voice_lang_id(wp.language);

    int rc = sense_voice_full_parallel(g_ctx, wp, samples, (int)samples.size(), 1);
    if (rc != 0) {
        fprintf(stderr, "[server] sense_voice_full_parallel returned %d\n", rc);
        return "";
    }

    // use_prefix=false → suppress <|zh|><|NEUTRAL|>… tokens for clean output
    return capture_stdout([&sp]() {
        sense_voice_print_output(g_ctx, sp.use_prefix, sp.use_itn);
    });
}

// ─────────────────────────────────────────────────────────────────────────────
// POST /v1/audio/transcriptions handler
// ─────────────────────────────────────────────────────────────────────────────

static void handle_transcription(const httplib::Request &req,
                                  httplib::Response      &res,
                                  const ServerParams     &sp) {
    // ── 1. Validate upload ────────────────────────────────────────────────────
    auto file_it = req.form.files.find("file");
    if (file_it == req.form.files.end()) {
        res.status = 400;
        res.set_content(json_err("Missing required field 'file'"), "application/json");
        return;
    }
    const auto &upload = file_it->second;
    if (upload.content.empty()) {
        res.status = 400;
        res.set_content(json_err("Uploaded 'file' is empty"), "application/json");
        return;
    }

    // ── 2. Parse optional fields (multipart form fields or query params) ──────
    auto field = [&](const char *name) -> std::string {
        // check multipart field (text also in field `files`)
        auto field_it = req.form.fields.find(name);
        if (field_it != req.form.fields.end()) {
            return field_it->second.content;
        }
        // check query params
        auto param_it = req.params.find(name);
        if (param_it != req.params.end()) {
            return param_it->second;
        }
        return "";
    };
    std::string language   = field("language");           // e.g. "zh", "en", "auto"
    std::string resp_fmt   = field("response_format");    // "json" | "text"
    bool        streaming  = (field("stream") == "true" || field("stream") == "1");
    if (resp_fmt.empty()) resp_fmt = "json";

    // ── 3. Decode audio → mono float32 @ SENSE_VOICE_SAMPLE_RATE ─────────────
    std::vector<char> data(upload.content.begin(), upload.content.end());
    auto pcm = decode_audio(data);
    if (pcm.empty()) {
        res.status = 400;
        res.set_content(
            json_err("Cannot decode audio. WAV (PCM-16/float32) is supported natively; "
                     "install ffmpeg for mp3/m4a/ogg/flac/webm."),
            "application/json");
        return;
    }

    // ── 4. Inference (serialised — context is not thread-safe) ───────────────
    std::string text;
    {
        std::lock_guard<std::mutex> lock(g_mtx);
        text = run_inference(pcm, language, sp);
    }

    // ── 5. Format and return response ─────────────────────────────────────────
    if (resp_fmt == "text") {
        res.set_content(text + "\n", "text/plain; charset=utf-8");
        return;
    }

    if (streaming) {
        // OpenAI streaming transcription — Server-Sent Events
        // SenseVoice is non-incremental, so we emit one delta then done.
        std::string body;
        body += "data: {\"type\":\"transcript.text.delta\",\"delta\":\""
              + json_escape(text) + "\"}\n\n";
        body += "data: {\"type\":\"transcript.text.done\",\"text\":\""
              + json_escape(text) + "\"}\n\n";
        body += "data: [DONE]\n\n";
        res.set_header("Cache-Control", "no-cache");
        res.set_content(body, "text/event-stream");
        return;
    }

    res.set_content(json_ok(text), "application/json");
}

// ─────────────────────────────────────────────────────────────────────────────
// CLI argument parsing
// ─────────────────────────────────────────────────────────────────────────────

static void print_usage(const char *prog) {
    fprintf(stderr,
        "Usage: %s [options]\n\n"
        "  -m, --model  PATH    path to SenseVoice GGML model file  [required]\n"
        "  -H, --host   HOST    listen address                       [0.0.0.0]\n"
        "  -p, --port   PORT    listen port                          [8080]\n"
        "  -t, --threads N      inference threads                    [auto up to 4]\n"
        "  -l, --language LANG  default language (auto/zh/en/ja/ko/yue) [auto]\n"
        "      --no-gpu         disable GPU inference\n"
        "      --flash-attn     enable flash attention\n"
        "      --itn            apply inverse text normalisation\n"
        "      --prefix         include language/emotion prefix tokens in output\n"
        "  -h, --help\n\n",
        prog);
}

static bool parse_args(int argc, char **argv, ServerParams &p) {
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        auto next = [&]() -> const char * {
            if (i + 1 >= argc) {
                fprintf(stderr, "error: missing argument for %s\n", a.c_str());
                exit(1);
            }
            return argv[++i];
        };
        if      (a == "-h" || a == "--help")       { print_usage(argv[0]); exit(0); }
        else if (a == "-m" || a == "--model")       p.model      = next();
        else if (a == "-H" || a == "--host")        p.host       = next();
        else if (a == "-p" || a == "--port")        p.port       = std::stoi(next());
        else if (a == "-t" || a == "--threads")     p.n_threads  = std::stoi(next());
        else if (a == "-l" || a == "--language")    p.language   = next();
        else if (a == "--no-gpu")                   p.use_gpu    = false;
        else if (a == "--flash-attn")               p.flash_attn = true;
        else if (a == "--itn")                      p.use_itn    = true;
        else if (a == "--prefix")                   p.use_prefix = true;
        else {
            fprintf(stderr, "error: unknown argument: %s\n", a.c_str());
            return false;
        }
    }
    return true;
}

// ─────────────────────────────────────────────────────────────────────────────
// main
// ─────────────────────────────────────────────────────────────────────────────

int main(int argc, char **argv) {
    ServerParams sp;
    if (!parse_args(argc, argv, sp)) {
        print_usage(argv[0]);
        return 1;
    }

    // ── Load model once at startup ────────────────────────────────────────────
    fprintf(stderr, "Loading model: %s\n", sp.model.c_str());

    sense_voice_context_params cparams = sense_voice_context_default_params();
    cparams.use_gpu    = sp.use_gpu;
    cparams.flash_attn = sp.flash_attn;
    cparams.use_itn    = sp.use_itn;

    g_ctx = sense_voice_small_init_from_file_with_params(sp.model.c_str(), cparams);
    if (!g_ctx) {
        fprintf(stderr, "error: failed to load model '%s'\n", sp.model.c_str());
        return 2;
    }
    g_ctx->language_id = sense_voice_lang_id(sp.language.c_str());
    fprintf(stderr, "Model ready — language: %s  threads: %d  gpu: %s\n",
            sp.language.c_str(), sp.n_threads, sp.use_gpu ? "yes" : "no");

    // ── Start HTTP server ─────────────────────────────────────────────────────
    httplib::Server svr;
    svr.set_payload_max_length(256 * 1024 * 1024);  // 256 MB upload cap

    svr.Post("/v1/audio/transcriptions",
        [&](const httplib::Request &req, httplib::Response &res) {
            handle_transcription(req, res, sp);
        });

    svr.Get("/health",
        [](const httplib::Request &, httplib::Response &res) {
            res.set_content(R"({"status":"ok"})", "application/json");
        });

    fprintf(stderr, "Listening on http://%s:%d\n\n", sp.host.c_str(), sp.port);
    if (!svr.listen(sp.host.c_str(), sp.port)) {
        fprintf(stderr, "error: cannot bind to %s:%d\n", sp.host.c_str(), sp.port);
        sv_free(g_ctx);
        return 3;
    }

    sv_free(g_ctx);
    return 0;
}