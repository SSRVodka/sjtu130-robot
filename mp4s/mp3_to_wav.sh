#!/bin/bash

cd "$(dirname "$0")" || exit 1

for mp3_file in *.mp3; do
    [ -e "$mp3_file" ] || continue

    wav_file="${mp3_file%.mp3}.wav"

    if [ -f "$wav_file" ]; then
        echo "✅ existed: $wav_file"
        continue
    fi

    echo "🔄 converting: $mp3_file -> $wav_file"
    ffmpeg -i "$mp3_file" -acodec pcm_s16le -ar 44100 -ac 2 "$wav_file" -hide_banner -loglevel error

    if [ $? -eq 0 ]; then
        echo "✅ converted: $wav_file"
    else
        echo "❌ failed: $mp3_file"
    fi

    echo "----------------------------------------"
done

echo -e "\n🎉 finished!"

