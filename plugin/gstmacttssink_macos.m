// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) 2026 dlgus8648

#import <AVFoundation/AVFoundation.h>
#import <Foundation/Foundation.h>
#include <stdlib.h>

#include "gstmacttssink_macos.h"

/* 일시정지/재개 설계 노트
 * --------------------------------------------------------------------------
 * AVSpeechSynthesizer의 pauseSpeakingAtBoundary:/continueSpeaking 은 반복
 * 사이클에서 신뢰할 수 없다(실측·알려진 macOS 결함). 빠른 일시정지/재개를
 * 누적하면 continueSpeaking 이 "한 단어만 말하고 스스로 다시 멈추는"(콜백도
 * 안 오는) 상태로 빠져, 동기 대기하는 render()가 영영 안 깨지는 데드락이
 * 생긴다. 그래서 합성기의 pause/continue 를 아예 쓰지 않는다.
 *
 * 대신 신뢰성 있는 stopSpeakingAtBoundary 만으로 구현한다:
 *   - 일시정지 = 현재 발화를 stop + 마지막으로 말한 단어 위치(resumeOffset)를 기록
 *   - 재개     = 그 청크를 resumeOffset 부터 다시 speak
 * willSpeakRange 로 단어 위치를 추적하므로 마지막 단어부터 자연스럽게 잇는다.
 * continueSpeaking 을 한 번도 거치지 않으므로 사이클이 쌓여도 데드락이 없다.
 */

@interface KbTtsDelegate : NSObject <AVSpeechSynthesizerDelegate>
@property (nonatomic, strong) NSCondition *cond;
@property (nonatomic, assign) BOOL done;        /* 현재 발화 종료(finish/cancel) */
@property (nonatomic, assign) BOOL cancelled;   /* stop — 청크 루프 전체 중단 */
@property (nonatomic, assign) BOOL paused;       /* 일시정지 — 재개까지 보류 */
@property (nonatomic, assign) BOOL interrupted;  /* 일시정지로 현재 발화가 끊김 → 같은 청크 재발화 */
@property (nonatomic, assign) NSUInteger resumeOffset;    /* 현재 청크 내 재개 오프셋(UTF-16) */
@property (nonatomic, assign) NSUInteger subBase;         /* 현재 발화가 청크 내에서 시작하는 오프셋 */
@property (nonatomic, assign) NSUInteger lastWordInChunk; /* 마지막으로 말한 단어의 청크 내 시작 */
@property (nonatomic, assign) NSUInteger chunkBase;       /* 현재 발화 시작의 전체 문자열 내 위치 */
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
  /* 일시정지(stop)·정지 양쪽에서 오는 콜백. 대기 중인 render()를 깨운다.
   * 일시정지였는지(=같은 청크 재발화) 정지였는지는 render()가 interrupted/
   * cancelled 플래그로 구분한다. */
  [self signalDone];
}

- (void)speechSynthesizer:(AVSpeechSynthesizer *)synthesizer
    willSpeakRangeOfSpeechString:(NSRange)characterRange
                       utterance:(AVSpeechUtterance *)utterance
{
  (void) synthesizer;
  (void) utterance;
  /* 이번 발화는 현재 청크의 subBase 위치부터 시작하는 부분 문자열이므로
   * 청크 내 절대 오프셋 = subBase + characterRange.location. 일시정지 시
   * 이 위치를 재개 지점으로 쓴다. */
  _lastWordInChunk = _subBase + characterRange.location;
  if (_wordCb) {
    /* 전체 문자열 기준 = chunkBase(= cr.location + subBase) + 발화 내 위치 */
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
    /* 합성기를 일시정지 상태로 두지 않으므로(우리는 stop+재발화만 씀) 단순
     * 정지로 충분하다. */
    if (handle.synth.isSpeaking) {
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
    KbTtsDelegate *del = handle.delegate;
    BOOL speaking = handle.synth.isSpeaking;
    [del.cond lock];
    if (del.cancelled) {
      [del.cond unlock];
      return;
    }
    del.paused = YES;
    if (speaking) {
      /* 현재 발화를 끊고, 마지막으로 말한 단어를 재개 지점으로 기록 →
       * 재개 시 그 단어부터 같은 청크를 다시 발화한다. */
      del.resumeOffset = del.lastWordInChunk;
      del.interrupted = YES;
    }
    [del.cond unlock];
    if (speaking) {
      /* didCancel → signalDone 으로 render()의 done 대기가 풀린다. */
      [handle.synth stopSpeakingAtBoundary:AVSpeechBoundaryImmediate];
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
    KbTtsDelegate *del = handle.delegate;
    [del.cond lock];
    del.paused = NO;
    [del.cond signal];  /* render()의 일시정지 대기를 깨워 같은 청크를 이어 발화 */
    [del.cond unlock];
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
    KbTtsDelegate *del = handle.delegate;
    /* 정지: 청크 루프를 중단하고 모든 대기(done/paused)를 직접 깨운다.
     * AVSpeech 콜백에 의존하지 않아야 데드락이 없다(콜백은 메인 스레드로
     * 오는데 정지가 메인 스레드를 블록할 수 있음). */
    [del.cond lock];
    del.cancelled = YES;
    del.paused = NO;
    del.done = YES;
    [del.cond signal];
    [del.cond unlock];
    if (handle.synth.isSpeaking) {
      [handle.synth stopSpeakingAtBoundary:AVSpeechBoundaryImmediate];
    }
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
    KbTtsDelegate *del = handle.delegate;
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

    del.wordCb = word_cb;
    del.wordCbUser = word_cb_user;
    [del.cond lock];
    del.cancelled = NO;
    del.paused = NO;
    del.interrupted = NO;
    del.resumeOffset = 0;
    [del.cond unlock];

    /* 문장 단위로 쪼개 순차 발화 — 짧은 발화라야 willSpeakRange가 단어별
     * 범위를 준다 (긴 단일 발화는 전체범위만 줌). 일시정지 시 같은 청크를
     * resumeOffset(마지막 단어)부터 다시 발화하므로 인덱스로 루프한다. */
    NSArray<NSValue *> *chunks = kb_split_sentences (text);
    NSCharacterSet *ws = [NSCharacterSet whitespaceCharacterSet];
    NSUInteger i = 0;
    while (i < chunks.count) {
      /* (A) 일시정지면 재개(또는 정지)까지 대기 */
      [del.cond lock];
      while (del.paused && !del.cancelled) {
        [del.cond wait];
      }
      BOOL stop = del.cancelled;
      NSUInteger off = del.resumeOffset;
      [del.cond unlock];
      if (stop) {
        break;
      }

      NSRange cr = [chunks[i] rangeValue];
      if (off > cr.length) {
        off = 0;
      }
      NSString *chunk = [text substringWithRange:cr];
      NSString *sub = (off > 0) ? [chunk substringFromIndex:off] : chunk;

      if ([[sub stringByTrimmingCharactersInSet:ws] length] == 0) {
        /* 남은 부분이 공백뿐 → 이 청크 완료로 보고 다음으로 */
        [del.cond lock];
        del.resumeOffset = 0;
        [del.cond unlock];
        i++;
        continue;
      }

      AVSpeechUtterance *utterance =
          [AVSpeechUtterance speechUtteranceWithString:sub];
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

      /* 단어 범위를 전체 문자열 기준으로 보정하기 위한 기준점.
       * subBase = 이번 발화가 청크 내에서 시작하는 오프셋(이어재생 위치). */
      del.subBase = off;
      del.chunkBase = cr.location + off;
      del.lastWordInChunk = off;

      [del.cond lock];
      del.done = NO;
      del.interrupted = NO;
      [del.cond unlock];

      [handle.synth speakUtterance:utterance];

      [del.cond lock];
      while (!del.done) {
        [del.cond wait];
      }
      BOOL wasCancelled = del.cancelled;
      BOOL wasInterrupted = del.interrupted;
      [del.cond unlock];

      if (wasCancelled) {
        break;
      }
      if (wasInterrupted) {
        /* 일시정지로 끊김 — 같은 청크(i)를 resumeOffset 부터 다시. 위 (A)에서
         * paused가 풀릴 때까지 기다린 뒤 재발화한다. */
        continue;
      }
      /* 자연 완료 → 다음 청크 */
      [del.cond lock];
      del.resumeOffset = 0;
      [del.cond unlock];
      i++;
    }

    del.wordCb = NULL;
    del.wordCbUser = NULL;
    return 0;
  }
}
