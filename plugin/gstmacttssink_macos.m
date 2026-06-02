// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) 2026 dlgus8648

#import <AVFoundation/AVFoundation.h>
#import <Foundation/Foundation.h>
#include <stdlib.h>

#include "gstmacttssink_macos.h"

@interface KbTtsDelegate : NSObject <AVSpeechSynthesizerDelegate>
@property (nonatomic, strong) NSCondition *cond;
@property (nonatomic, assign) BOOL done;
@property (nonatomic, assign) BOOL cancelled;      /* stop 시 청크 루프 중단 */
@property (nonatomic, assign) NSUInteger chunkBase; /* 현재 청크의 전체 문자열 내 시작(UTF-16) */
@property (nonatomic, assign) mac_tts_word_cb wordCb;
@property (nonatomic, assign) void *wordCbUser;
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

- (void)speechSynthesizer:(AVSpeechSynthesizer *)synthesizer
    willSpeakRangeOfSpeechString:(NSRange)characterRange
                       utterance:(AVSpeechUtterance *)utterance
{
  (void) synthesizer;
  (void) utterance;
  if (_wordCb) {
    /* 청크(문장) 단위로 말하므로 범위는 청크 기준 → 전체 문자열 기준으로
     * 보정(chunkBase). 그래야 GUI가 원본 위치로 되돌릴 수 있다. */
    _wordCb (_wordCbUser, (unsigned int) (_chunkBase + characterRange.location),
        (unsigned int) characterRange.length);
  }
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
      /* 일시정지 상태에서 stop은 콜백(didCancel)이 안 오는 알려진 quirk가
       * 있어, 먼저 continueSpeaking으로 재개한 뒤 즉시 정지한다. */
      if (handle.synth.isPaused) {
        [handle.synth continueSpeaking];
      }
      [handle.synth stopSpeakingAtBoundary:AVSpeechBoundaryImmediate];
    }
    handle.synth.delegate = nil;
    handle.synth = nil;
    handle.delegate = nil;
  }
}

void
mac_tts_pause (mac_tts_ctx *ctx)
{
  if (!ctx) {
    return;
  }
  @autoreleasepool {
    KbTtsHandle *handle = (__bridge KbTtsHandle *) ctx;
    if (handle.synth.isSpeaking && !handle.synth.isPaused) {
      [handle.synth pauseSpeakingAtBoundary:AVSpeechBoundaryWord];
    }
  }
}

void
mac_tts_resume (mac_tts_ctx *ctx)
{
  if (!ctx) {
    return;
  }
  @autoreleasepool {
    KbTtsHandle *handle = (__bridge KbTtsHandle *) ctx;
    if (handle.synth.isPaused) {
      [handle.synth continueSpeaking];
    }
  }
}

void
mac_tts_cancel (mac_tts_ctx *ctx)
{
  if (!ctx) {
    return;
  }
  @autoreleasepool {
    KbTtsHandle *handle = (__bridge KbTtsHandle *) ctx;
    if (handle.synth.isSpeaking) {
      /* 일시정지 상태면 stop 콜백이 안 오는 quirk 대비 먼저 재개 */
      if (handle.synth.isPaused) {
        [handle.synth continueSpeaking];
      }
      [handle.synth stopSpeakingAtBoundary:AVSpeechBoundaryImmediate];
    }
    /* 중요: AVSpeech의 didCancel 콜백은 메인 스레드로 전달되는데, 정지(state
     * 변경)는 메인 스레드를 블록한다 → 콜백이 안 와서 render()의 cond 대기가
     * 영영 안 깨지는 데드락. 그래서 콜백에 의존하지 않고 대기 중인 render()를
     * 여기서 직접 깨운다. (뒤늦게 didCancel이 와도 done은 이미 YES라 무해.) */
    [handle.delegate.cond lock];
    handle.delegate.cancelled = YES;  /* 청크 루프도 중단 */
    handle.delegate.done = YES;
    [handle.delegate.cond signal];
    [handle.delegate.cond unlock];
  }
}

/* 텍스트를 문장 단위 청크(전체 문자열 내 NSRange)로 분할.
 * AVSpeech는 긴 단일 발화엔 willSpeakRange를 "전체 범위"로만 줘서(실측)
 * 단어 하이라이트가 안 된다. 문장처럼 짧게 쪼개 발화하면 단어별 범위가
 * 나온다. 종결부호(.!?…) 직후에서 끊고, 한 문장이 MAX를 넘으면 공백에서
 * 강제 분할. 종결부호 뒤 공백은 그 청크에 포함. */
static NSArray<NSValue *> *
kb_split_sentences (NSString *text)
{
  const NSUInteger MAX = 80;  /* 이보다 길면 AVSpeech가 전체범위로 보고할 위험 */
  NSCharacterSet *enders =
      [NSCharacterSet characterSetWithCharactersInString:@".!?…。！？"];
  NSCharacterSet *ws = [NSCharacterSet whitespaceCharacterSet];
  NSMutableArray<NSValue *> *out = [NSMutableArray array];
  NSUInteger n = text.length;
  NSUInteger start = 0;
  NSUInteger i = 0;

  while (i < n) {
    unichar c = [text characterAtIndex:i];
    if ([enders characterIsMember:c]) {
      NSUInteger end = i + 1;
      while (end < n && [ws characterIsMember:[text characterAtIndex:end]]) {
        end++;
      }
      [out addObject:[NSValue valueWithRange:NSMakeRange (start, end - start)]];
      start = end;
      i = end;
    } else if (i - start + 1 >= MAX) {
      /* 너무 긴 문장 — 마지막 공백에서 끊기, 없으면 강제 */
      NSRange sp = [text rangeOfCharacterFromSet:ws
                                         options:NSBackwardsSearch
                                           range:NSMakeRange (start, i - start + 1)];
      NSUInteger cut = (sp.location != NSNotFound && sp.location > start)
                           ? sp.location + 1
                           : i + 1;
      [out addObject:[NSValue valueWithRange:NSMakeRange (start, cut - start)]];
      start = cut;
      i = cut;
    } else {
      i++;
    }
  }
  if (start < n) {
    [out addObject:[NSValue valueWithRange:NSMakeRange (start, n - start)]];
  }
  return out;
}

int
mac_tts_speak (mac_tts_ctx *ctx, const char *utf8_text,
               const mac_tts_options *opts,
               mac_tts_word_cb word_cb, void *word_cb_user)
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

    /* voice는 1회만 해석 (모든 청크 공통) */
    AVSpeechSynthesisVoice *voice = nil;
    if (opts && opts->voice_id && opts->voice_id[0] != '\0') {
      NSString *vid = [NSString stringWithUTF8String:opts->voice_id];
      if (vid) {
        /* identifier (dotted form) 우선, 실패 시 language code로 fallback */
        voice = [AVSpeechSynthesisVoice voiceWithIdentifier:vid];
        if (!voice) {
          voice = [AVSpeechSynthesisVoice voiceWithLanguage:vid];
        }
      }
    }

    handle.delegate.wordCb = word_cb;
    handle.delegate.wordCbUser = word_cb_user;
    handle.delegate.cancelled = NO;

    /* 문장 단위로 쪼개 순차 발화 — 짧은 발화라야 willSpeakRange가 단어별
     * 범위를 준다 (긴 단일 발화는 전체범위만 줌). 각 청크의 시작 위치를
     * chunkBase로 넘겨 단어 범위를 전체 문자열 기준으로 보정. */
    NSArray<NSValue *> *chunks = kb_split_sentences (text);
    for (NSValue *cv in chunks) {
      NSRange cr = cv.rangeValue;
      if (handle.delegate.cancelled) {
        break;
      }
      NSString *chunk = [text substringWithRange:cr];
      if ([chunk stringByTrimmingCharactersInSet:
                     [NSCharacterSet whitespaceCharacterSet]].length == 0) {
        continue;  /* 공백뿐인 청크 skip */
      }

      AVSpeechUtterance *utterance =
          [AVSpeechUtterance speechUtteranceWithString:chunk];
      /* didFinish가 audio flush보다 먼저 와서 마지막 음절(한국어 받침)이
       * 잘리는 것 방지 — 각 청크 끝에 짧은 지연. */
      utterance.postUtteranceDelay = 0.25;
      if (opts) {
        utterance.rate            = opts->rate;
        utterance.pitchMultiplier = opts->pitch;
        utterance.volume          = opts->volume;
      }
      if (voice) {
        utterance.voice = voice;
      }

      handle.delegate.chunkBase = cr.location;

      [handle.delegate.cond lock];
      handle.delegate.done = NO;
      [handle.delegate.cond unlock];

      [handle.synth speakUtterance:utterance];

      [handle.delegate.cond lock];
      while (!handle.delegate.done) {
        [handle.delegate.cond wait];
      }
      [handle.delegate.cond unlock];

      if (handle.delegate.cancelled) {
        break;
      }
    }

    handle.delegate.wordCb = NULL;
    handle.delegate.wordCbUser = NULL;
    return 0;
  }
}
