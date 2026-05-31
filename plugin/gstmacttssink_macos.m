// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) 2026 dlgus8648

#import <AVFoundation/AVFoundation.h>
#import <Foundation/Foundation.h>
#include <stdlib.h>

#include "gstmacttssink_macos.h"

@interface KbTtsDelegate : NSObject <AVSpeechSynthesizerDelegate>
@property (nonatomic, strong) NSCondition *cond;
@property (nonatomic, assign) BOOL done;
@end

@implementation KbTtsDelegate
- (instancetype)init
{
  if ((self = [super init])) {
    _cond = [[NSCondition alloc] init];
    _done = NO;
  }
  return self;
}

- (void)signalDone
{
  [_cond lock];
  _done = YES;
  [_cond signal];
  [_cond unlock];
}

- (void)speechSynthesizer:(AVSpeechSynthesizer *)synthesizer
    didFinishSpeechUtterance:(AVSpeechUtterance *)utterance
{
  (void) synthesizer;
  (void) utterance;
  [self signalDone];
}

- (void)speechSynthesizer:(AVSpeechSynthesizer *)synthesizer
    didCancelSpeechUtterance:(AVSpeechUtterance *)utterance
{
  (void) synthesizer;
  (void) utterance;
  [self signalDone];
}
@end

@interface KbTtsHandle : NSObject
@property (nonatomic, strong) AVSpeechSynthesizer *synth;
@property (nonatomic, strong) KbTtsDelegate *delegate;
@end

@implementation KbTtsHandle
@end

mac_tts_ctx *
mac_tts_init (void)
{
  @autoreleasepool {
    KbTtsHandle *handle = [[KbTtsHandle alloc] init];
    handle.synth = [[AVSpeechSynthesizer alloc] init];
    handle.delegate = [[KbTtsDelegate alloc] init];
    handle.synth.delegate = handle.delegate;
    /* Transfer ownership to caller; mac_tts_shutdown() reclaims it. */
    return (mac_tts_ctx *) CFBridgingRetain (handle);
  }
}

void
mac_tts_shutdown (mac_tts_ctx *ctx)
{
  if (!ctx) {
    return;
  }
  @autoreleasepool {
    KbTtsHandle *handle = (__bridge_transfer KbTtsHandle *) ctx;
    if (handle.synth.isSpeaking) {
      [handle.synth stopSpeakingAtBoundary:AVSpeechBoundaryImmediate];
    }
    handle.synth.delegate = nil;
    handle.synth = nil;
    handle.delegate = nil;
  }
}

int
mac_tts_speak (mac_tts_ctx *ctx, const char *utf8_text,
               const mac_tts_options *opts)
{
  if (!ctx || !utf8_text) {
    return -1;
  }
  @autoreleasepool {
    KbTtsHandle *handle = (__bridge KbTtsHandle *) ctx;
    NSString *text = [NSString stringWithUTF8String:utf8_text];
    if (!text || text.length == 0) {
      return -1;
    }

    AVSpeechUtterance *utterance = [AVSpeechUtterance speechUtteranceWithString:text];

    /* AVSpeech의 didFinishSpeechUtterance: 콜백이 audio buffer flush보다
     * 먼저 호출되는 경우가 있어 마지막 음절(특히 한국어 받침)이 잘림.
     * postUtteranceDelay로 콜백을 늦춰 audio가 완전히 끝날 시간을 확보. */
    utterance.postUtteranceDelay = 0.25;

    if (opts) {
      utterance.rate            = opts->rate;
      utterance.pitchMultiplier = opts->pitch;
      utterance.volume          = opts->volume;

      if (opts->voice_id && opts->voice_id[0] != '\0') {
        NSString *vid = [NSString stringWithUTF8String:opts->voice_id];
        if (vid) {
          /* identifier (dotted form) 우선, 실패 시 language code로 fallback */
          AVSpeechSynthesisVoice *voice =
              [AVSpeechSynthesisVoice voiceWithIdentifier:vid];
          if (!voice) {
            voice = [AVSpeechSynthesisVoice voiceWithLanguage:vid];
          }
          if (voice) {
            utterance.voice = voice;
          }
        }
      }
    }

    [handle.delegate.cond lock];
    handle.delegate.done = NO;
    [handle.delegate.cond unlock];

    [handle.synth speakUtterance:utterance];

    [handle.delegate.cond lock];
    while (!handle.delegate.done) {
      [handle.delegate.cond wait];
    }
    [handle.delegate.cond unlock];

    return 0;
  }
}
