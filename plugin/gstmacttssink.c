// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) 2026 dlgus8648

#include <gst/gst.h>
#include <gst/base/gstbasesink.h>
#include <string.h>

#include "gstmacttssink_macos.h"

GST_DEBUG_CATEGORY_STATIC (gst_mac_tts_sink_debug);
#define GST_CAT_DEFAULT gst_mac_tts_sink_debug

#define GST_TYPE_MAC_TTS_SINK (gst_mac_tts_sink_get_type ())
G_DECLARE_FINAL_TYPE (GstMacTtsSink, gst_mac_tts_sink, GST, MAC_TTS_SINK, GstBaseSink)

enum
{
  PROP_0,
  PROP_RATE,
  PROP_PITCH,
  PROP_VOLUME,
  PROP_VOICE,
};

#define DEFAULT_RATE   0.5f
#define DEFAULT_PITCH  1.0f
#define DEFAULT_VOLUME 1.0f

struct _GstMacTtsSink
{
  GstBaseSink parent;
  mac_tts_ctx *tts;

  gfloat rate;
  gfloat pitch;
  gfloat volume;
  gchar *voice;                 /* NULL = system default */
};

G_DEFINE_TYPE (GstMacTtsSink, gst_mac_tts_sink, GST_TYPE_BASE_SINK)

static GstStaticPadTemplate sink_template = GST_STATIC_PAD_TEMPLATE (
    "sink",
    GST_PAD_SINK,
    GST_PAD_ALWAYS,
    GST_STATIC_CAPS ("text/x-raw, format=(string)utf8")
);

/* --- property accessors --------------------------------------------------- */

static void
gst_mac_tts_sink_set_property (GObject * object, guint id,
    const GValue * value, GParamSpec * pspec)
{
  GstMacTtsSink *self = GST_MAC_TTS_SINK (object);

  switch (id) {
    case PROP_RATE:
      self->rate = g_value_get_float (value);
      break;
    case PROP_PITCH:
      self->pitch = g_value_get_float (value);
      break;
    case PROP_VOLUME:
      self->volume = g_value_get_float (value);
      break;
    case PROP_VOICE:
      g_free (self->voice);
      self->voice = g_value_dup_string (value);
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, id, pspec);
      break;
  }
}

static void
gst_mac_tts_sink_get_property (GObject * object, guint id,
    GValue * value, GParamSpec * pspec)
{
  GstMacTtsSink *self = GST_MAC_TTS_SINK (object);

  switch (id) {
    case PROP_RATE:
      g_value_set_float (value, self->rate);
      break;
    case PROP_PITCH:
      g_value_set_float (value, self->pitch);
      break;
    case PROP_VOLUME:
      g_value_set_float (value, self->volume);
      break;
    case PROP_VOICE:
      g_value_set_string (value, self->voice);
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, id, pspec);
      break;
  }
}

static void
gst_mac_tts_sink_finalize (GObject * object)
{
  GstMacTtsSink *self = GST_MAC_TTS_SINK (object);
  g_free (self->voice);
  self->voice = NULL;
  G_OBJECT_CLASS (gst_mac_tts_sink_parent_class)->finalize (object);
}

/* --- BaseSink overrides --------------------------------------------------- */

static gboolean
gst_mac_tts_sink_start (GstBaseSink * sink)
{
  GstMacTtsSink *self = GST_MAC_TTS_SINK (sink);
  GST_DEBUG_OBJECT (self, "start()");

  self->tts = mac_tts_init ();
  if (!self->tts) {
    GST_ERROR_OBJECT (self, "mac_tts_init() failed");
    return FALSE;
  }
  return TRUE;
}

static gboolean
gst_mac_tts_sink_stop (GstBaseSink * sink)
{
  GstMacTtsSink *self = GST_MAC_TTS_SINK (sink);
  GST_DEBUG_OBJECT (self, "stop()");

  if (self->tts) {
    mac_tts_shutdown (self->tts);
    self->tts = NULL;
  }
  return TRUE;
}

/* render()가 mac_tts_speak()에서 동기 블록 대기 중일 때, 상태 변경(정지/
 * flush)으로 빠져나와야 하면 basesink가 unlock()을 부른다. 현재 발화를
 * 즉시 취소해 블록된 render()가 리턴하도록 한다 (구현 안 하면 in-process
 * 정지가 데드락). 컨텍스트는 부수지 않음(정리는 stop()에서). */
static gboolean
gst_mac_tts_sink_unlock (GstBaseSink * sink)
{
  GstMacTtsSink *self = GST_MAC_TTS_SINK (sink);
  GST_DEBUG_OBJECT (self, "unlock()");
  if (self->tts) {
    mac_tts_cancel (self->tts);
  }
  return TRUE;
}

/* mac_tts_speak가 각 단어를 말하기 직전 호출. 단어 범위(읽는 문자열의
 * UTF-16 코드유닛 기준)를 "annoyspeaker-word" element 메시지로 버스에 post.
 * GUI(인프로세스 PyGObject)가 버스를 폴링해 실시간 하이라이트에 사용. */
static void
gst_mac_tts_sink_on_word (void *user_data, guint start, guint length)
{
  GstMacTtsSink *self = GST_MAC_TTS_SINK (user_data);
  gst_element_post_message (GST_ELEMENT (self),
      gst_message_new_element (GST_OBJECT (self),
          gst_structure_new ("annoyspeaker-word",
              "start", G_TYPE_UINT, start,
              "end", G_TYPE_UINT, start + length,
              NULL)));
}

static GstFlowReturn
gst_mac_tts_sink_render (GstBaseSink * sink, GstBuffer * buffer)
{
  GstMacTtsSink *self = GST_MAC_TTS_SINK (sink);
  GstMapInfo map;

  if (!gst_buffer_map (buffer, &map, GST_MAP_READ)) {
    GST_ERROR_OBJECT (self, "failed to map buffer");
    return GST_FLOW_ERROR;
  }

  gchar *text = g_strndup ((const gchar *) map.data, map.size);

  /* AVSpeechSynthesizer는 빈/공백 utterance에 완료 콜백을 안 줘서
   * 동기 대기가 무한정 됨. 다만 strip하지 않는다 — trailing 공백은
   * 한국어 끝 음절(특히 받침 있는 글자)이 trail off되며 잘리는 현상의
   * 안전 패딩 역할이라, GUI에서 의도적으로 붙여 보낼 수 있음. */
  gboolean has_content = FALSE;
  for (const gchar *p = text; *p; ++p) {
    if (!g_ascii_isspace ((guchar) *p)) {
      has_content = TRUE;
      break;
    }
  }

  if (has_content) {
    mac_tts_options opts = {
      .rate     = self->rate,
      .pitch    = self->pitch,
      .volume   = self->volume,
      .voice_id = self->voice,
    };
    GST_DEBUG_OBJECT (self,
        "speaking (%zu bytes, rate=%.2f pitch=%.2f vol=%.2f voice=%s)",
        strlen (text), opts.rate, opts.pitch, opts.volume,
        opts.voice_id ? opts.voice_id : "(default)");

    if (self->tts && mac_tts_speak (self->tts, text, &opts,
            gst_mac_tts_sink_on_word, self) != 0) {
      GST_WARNING_OBJECT (self, "mac_tts_speak() failed for: %s", text);
    }
  } else {
    GST_DEBUG_OBJECT (self, "empty/whitespace-only text buffer, skipping");
  }

  /* 이 버퍼(=utterance) 합성 완료를 GUI에 알림. 인프로세스 재생에서
   * EOS+blocking 타이밍에 의존하지 않고 "재생 끝"을 인지하게 한다.
   * (현재 GUI는 텍스트 전체를 1버퍼로 보내므로 done도 1회.) */
  gst_element_post_message (GST_ELEMENT (self),
      gst_message_new_element (GST_OBJECT (self),
          gst_structure_new_empty ("annoyspeaker-done")));

  g_free (text);
  gst_buffer_unmap (buffer, &map);
  return GST_FLOW_OK;
}

/* --- action signals: pause / resume --------------------------------------- */

/* GUI가 element.emit("pause"/"resume")로 호출 (G_SIGNAL_ACTION).
 * render()가 스트리밍 스레드에서 블록 대기 중일 때 GUI 스레드에서 불려
 * 합성기를 단어 경계에서 멈추거나 재개한다. */
static void
gst_mac_tts_sink_pause (GstMacTtsSink * self)
{
  if (self->tts) {
    mac_tts_pause (self->tts);
  }
}

static void
gst_mac_tts_sink_resume (GstMacTtsSink * self)
{
  if (self->tts) {
    mac_tts_resume (self->tts);
  }
}

/* --- class / instance init ------------------------------------------------ */

static void
gst_mac_tts_sink_class_init (GstMacTtsSinkClass * klass)
{
  GObjectClass *object_class = G_OBJECT_CLASS (klass);
  GstElementClass *element_class = GST_ELEMENT_CLASS (klass);
  GstBaseSinkClass *base_sink_class = GST_BASE_SINK_CLASS (klass);

  object_class->set_property = gst_mac_tts_sink_set_property;
  object_class->get_property = gst_mac_tts_sink_get_property;
  object_class->finalize     = gst_mac_tts_sink_finalize;

  g_object_class_install_property (object_class, PROP_RATE,
      g_param_spec_float ("rate", "Rate",
          "Speaking rate (0.0 = slowest, 1.0 = fastest, 0.5 = default)",
          0.0f, 1.0f, DEFAULT_RATE,
          G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));

  g_object_class_install_property (object_class, PROP_PITCH,
      g_param_spec_float ("pitch", "Pitch multiplier",
          "Pitch multiplier (0.5 = low, 2.0 = high, 1.0 = default)",
          0.5f, 2.0f, DEFAULT_PITCH,
          G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));

  g_object_class_install_property (object_class, PROP_VOLUME,
      g_param_spec_float ("volume", "Volume",
          "Volume (0.0 = silent, 1.0 = full, default = 1.0)",
          0.0f, 1.0f, DEFAULT_VOLUME,
          G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));

  g_object_class_install_property (object_class, PROP_VOICE,
      g_param_spec_string ("voice", "Voice",
          "Voice identifier or language code (e.g. \"ko-KR\", "
          "\"com.apple.voice.compact.ko-KR.Yuna\"). NULL = system default.",
          NULL,
          G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));

  gst_element_class_set_static_metadata (element_class,
      "macOS TTS element",
      "Sink/Text",
      "Sink a text buffer and synthesise speech via macOS AVSpeechSynthesizer",
      "AnnoySpeaker <noreply@example.com>");

  gst_element_class_add_static_pad_template (element_class, &sink_template);

  /* GUI가 호출할 일시정지/재개 액션 시그널 */
  g_signal_new_class_handler ("pause", G_TYPE_FROM_CLASS (klass),
      G_SIGNAL_RUN_LAST | G_SIGNAL_ACTION,
      G_CALLBACK (gst_mac_tts_sink_pause), NULL, NULL, NULL,
      G_TYPE_NONE, 0);
  g_signal_new_class_handler ("resume", G_TYPE_FROM_CLASS (klass),
      G_SIGNAL_RUN_LAST | G_SIGNAL_ACTION,
      G_CALLBACK (gst_mac_tts_sink_resume), NULL, NULL, NULL,
      G_TYPE_NONE, 0);

  base_sink_class->unlock = GST_DEBUG_FUNCPTR (gst_mac_tts_sink_unlock);
  base_sink_class->start  = GST_DEBUG_FUNCPTR (gst_mac_tts_sink_start);
  base_sink_class->stop   = GST_DEBUG_FUNCPTR (gst_mac_tts_sink_stop);
  base_sink_class->render = GST_DEBUG_FUNCPTR (gst_mac_tts_sink_render);
}

static void
gst_mac_tts_sink_init (GstMacTtsSink * self)
{
  self->tts    = NULL;
  self->rate   = DEFAULT_RATE;
  self->pitch  = DEFAULT_PITCH;
  self->volume = DEFAULT_VOLUME;
  self->voice  = NULL;
}

/* --- plugin entry --------------------------------------------------------- */

static gboolean
plugin_init (GstPlugin * plugin)
{
  GST_DEBUG_CATEGORY_INIT (gst_mac_tts_sink_debug, "macttssink", 0,
      "macOS TTS sink (C, AVSpeechSynthesizer)");
  return gst_element_register (plugin, "macttssink", GST_RANK_NONE,
      GST_TYPE_MAC_TTS_SINK);
}

#ifndef PACKAGE
#define PACKAGE "gst-macttssink-c"
#endif

GST_PLUGIN_DEFINE (
    GST_VERSION_MAJOR,
    GST_VERSION_MINOR,
    macttssink,
    "macOS TTS sink (C, AVSpeechSynthesizer)",
    plugin_init,
    "0.3.0",
    "LGPL",
    PACKAGE,
    "https://github.com/gstreamer101/AnnoySpeaker"
)
