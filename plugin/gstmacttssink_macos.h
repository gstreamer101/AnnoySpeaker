// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) 2026 dlgus8648

#ifndef GSTMACTTSSINK_MACOS_H
#define GSTMACTTSSINK_MACOS_H

#ifdef __cplusplus
extern "C" {
#endif

/* Opaque handle. Created by mac_tts_init(), destroyed by mac_tts_shutdown(). */
typedef struct mac_tts_ctx mac_tts_ctx;

/* Utterance options. Match AVSpeechUtterance properties.
 *   rate:     0.0..1.0  (AVSpeech default ≈ 0.5)
 *   pitch:    0.5..2.0  (default 1.0)
 *   volume:   0.0..1.0  (default 1.0)
 *   voice_id: NULL = system default voice for current locale
 *             "ko-KR" / "en-US" style language code, OR
 *             "com.apple.voice.compact.ko-KR.Yuna" style identifier
 */
typedef struct {
  float       rate;
  float       pitch;
  float       volume;
  const char *voice_id;
} mac_tts_options;

#define MAC_TTS_OPTIONS_DEFAULTS { 0.5f, 1.0f, 1.0f, NULL }

mac_tts_ctx *mac_tts_init(void);
void         mac_tts_shutdown(mac_tts_ctx *ctx);

/* Speak the given UTF-8 text with the given options (NULL = defaults).
 * Blocks until playback finishes. Returns 0 on success, non-zero on failure. */
int          mac_tts_speak(mac_tts_ctx *ctx, const char *utf8_text,
                           const mac_tts_options *opts);

#ifdef __cplusplus
}
#endif

#endif /* GSTMACTTSSINK_MACOS_H */
