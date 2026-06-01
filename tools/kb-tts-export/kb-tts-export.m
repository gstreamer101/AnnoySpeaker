// SPDX-License-Identifier: MIT
// Copyright (c) 2026 dlgus8648

/* kb-tts-export: Synthesize stdin text to an .m4a file via AVSpeechSynthesizer.
 *
 * 텍스트가 매우 길면 AVSpeech의 writeUtterance:toBufferCallback:가 첫 buffer
 * 생성 전 내부 처리에 비선형적으로 오랜 시간을 씀. 그래서 stdin을 줄 단위로
 * 쪼개 여러 utterance를 sequential 처리하면서 같은 m4a 파일에 누적 write.
 *
 * Usage:
 *   echo "안녕하세요" | kb-tts-export --out file.m4a [options]
 *
 * Options:
 *   --out <path>       output m4a file (required)
 *   --rate <0.0-1.0>   AVSpeechUtterance.rate (default 0.5)
 *   --pitch <0.5-2.0>  pitchMultiplier (default 1.0)
 *   --volume <0.0-1.0> volume (default 1.0)
 *   --voice <id>       AVSpeechSynthesisVoice identifier or language code
 */

#import <AVFoundation/AVFoundation.h>
#import <Foundation/Foundation.h>
#include <stdio.h>
#include <stdlib.h>

static void
print_usage (const char *prog)
{
  fprintf (stderr,
      "Usage: %s --out <file.m4a> [options] < text-from-stdin\n"
      "\n"
      "Options:\n"
      "  --out <path>        output m4a file (required)\n"
      "  --rate <0.0-1.0>    speaking rate (default 0.5 = AVSpeech default)\n"
      "  --pitch <0.5-2.0>   pitch multiplier (default 1.0)\n"
      "  --volume <0.0-1.0>  volume (default 1.0)\n"
      "  --voice <id>        voice identifier or BCP-47 language code\n"
      "                      e.g. \"ko-KR\" or\n"
      "                           \"com.apple.voice.compact.ko-KR.Yuna\"\n"
      "  --list-voices       print installed voices and exit. One per line:\n"
      "                      <identifier>\\t<name>\\t<language>\\t<quality>\n",
      prog);
}

/* 설치된 AVSpeech 음성을 한 줄에 하나씩 stdout으로 출력.
 * 형식: identifier<TAB>name<TAB>language<TAB>quality
 * quality: default | enhanced | premium.
 * GUI가 이 출력을 파싱해 음성 선택 드롭다운을 채운다. */
static int
list_voices (void)
{
  for (AVSpeechSynthesisVoice *v in [AVSpeechSynthesisVoice speechVoices]) {
    /* quality는 NSInteger: 1=Default, 2=Enhanced, 3=Premium.
     * Premium 심볼을 직접 참조하면 -Wunguarded-availability가 뜰 수 있어
     * 정수값으로 비교한다. */
    const char *quality = "default";
    if ((long) v.quality == 2) {
      quality = "enhanced";
    } else if ((long) v.quality >= 3) {
      quality = "premium";
    }
    fprintf (stdout, "%s\t%s\t%s\t%s\n",
        v.identifier.UTF8String, v.name.UTF8String,
        v.language.UTF8String, quality);
  }
  return 0;
}

static NSString *
read_stdin_utf8 (void)
{
  NSFileHandle *fh = [NSFileHandle fileHandleWithStandardInput];
  NSData *data = [fh readDataToEndOfFile];
  if (!data || data.length == 0) {
    return nil;
  }
  return [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
}

/* 텍스트를 줄 단위로 모으되 누적 길이가 MAX_CHUNK_CHARS를 넘으면 새 chunk로
 * flush. 빈 줄(단락 구분)에서도 강제 flush. 각 chunk 끝에 한국어 잘림 방지
 * 안전 패딩 " ,," 부착.
 *
 * 너무 작은 chunk(한 줄당 한 utterance)면 AVSpeech 초기화 오버헤드가 누적되어
 * 느려지고, 너무 큰 chunk(전체 한 utterance)면 AVSpeech가 비선형으로 폭증.
 * ~1500자가 측정상 안정적 sweet spot (1500자는 약 1초).
 */
#define MAX_CHUNK_CHARS 1500

/* 매우 긴 단일 줄을 MAX_CHUNK_CHARS 이내 part로 분할.
 * 자연 분할점(문장 종결 → 공백) 우선, 못 찾으면 강제로 자름.
 * 코드 블록, 표 행, 줄바꿈 없이 긴 영어 등이 한 줄에 수천자로
 * 들어와도 chunk 단일 utterance 비선형 폭증을 방지. */
static NSArray<NSString *> *
split_long_line (NSString *line)
{
  NSMutableArray<NSString *> *parts = [NSMutableArray array];
  NSCharacterSet *sentence_ends =
      [NSCharacterSet characterSetWithCharactersInString:@".!?…。！？"];
  NSCharacterSet *whitespace = [NSCharacterSet whitespaceCharacterSet];

  NSUInteger pos = 0;
  while (pos < line.length) {
    NSUInteger remain = line.length - pos;
    if (remain <= MAX_CHUNK_CHARS) {
      [parts addObject:[line substringFromIndex:pos]];
      break;
    }

    NSRange search = NSMakeRange (pos, MAX_CHUNK_CHARS);
    /* 1) 문장 종결(.!?) 가장 마지막 */
    NSRange r1 = [line rangeOfCharacterFromSet:sentence_ends
                                       options:NSBackwardsSearch
                                         range:search];
    NSUInteger cut = NSNotFound;
    if (r1.location != NSNotFound
        && r1.location > pos + MAX_CHUNK_CHARS / 3) {
      cut = r1.location + r1.length;  /* 종결문자 포함 */
    } else {
      /* 2) 공백 가장 마지막 */
      NSRange r2 = [line rangeOfCharacterFromSet:whitespace
                                         options:NSBackwardsSearch
                                           range:search];
      if (r2.location != NSNotFound
          && r2.location > pos + MAX_CHUNK_CHARS / 3) {
        cut = r2.location + r2.length;
      }
    }
    if (cut == NSNotFound) {
      /* 3) 분할점 없음 — 강제로 자름 */
      cut = pos + MAX_CHUNK_CHARS;
    }

    [parts addObject:[line substringWithRange:NSMakeRange (pos, cut - pos)]];
    pos = cut;
  }
  return parts;
}

static NSArray<NSString *> *
split_into_chunks (NSString *text)
{
  NSCharacterSet *ws = [NSCharacterSet whitespaceCharacterSet];
  NSMutableArray<NSString *> *chunks = [NSMutableArray array];
  NSMutableString *current = [NSMutableString string];

  NSArray<NSString *> *lines =
      [text componentsSeparatedByCharactersInSet:
                [NSCharacterSet newlineCharacterSet]];

  for (NSString *raw in lines) {
    NSString *line = [raw stringByTrimmingCharactersInSet:ws];

    if (line.length == 0) {
      /* 빈 줄 = 단락 구분 → 현재 chunk 종료 */
      if (current.length > 0) {
        [chunks addObject:[current stringByAppendingString:@" ,,"]];
        [current setString:@""];
      }
      continue;
    }

    /* 한 줄 자체가 너무 길면 먼저 part 단위로 분할 */
    NSArray<NSString *> *parts = (line.length > MAX_CHUNK_CHARS)
        ? split_long_line (line)
        : @[ line ];

    for (NSString *part in parts) {
      /* 추가 시 너무 커지면 먼저 flush */
      if (current.length > 0
          && current.length + part.length + 2 > MAX_CHUNK_CHARS) {
        [chunks addObject:[current stringByAppendingString:@" ,,"]];
        [current setString:@""];
      }

      if (current.length > 0) {
        [current appendString:@". "];  /* 사이 자연 휴식 */
      }
      [current appendString:part];
    }
  }

  if (current.length > 0) {
    [chunks addObject:[current stringByAppendingString:@" ,,"]];
  }

  return chunks;
}

static AVSpeechUtterance *
make_utterance (NSString *text, float rate, float pitch, float volume,
                AVSpeechSynthesisVoice *voice)
{
  AVSpeechUtterance *u = [AVSpeechUtterance speechUtteranceWithString:text];
  u.rate = rate;
  u.pitchMultiplier = pitch;
  u.volume = volume;
  u.postUtteranceDelay = 0.25;
  if (voice) {
    u.voice = voice;
  }
  return u;
}

/* 한 utterance를 합성해 wav 파일에 누적 쓰기. wav_file이 nil이면
 * 첫 buffer 받을 때 PCM Linear 포맷으로 생성. 에러는 *err_out 으로 반환. */
static int
speak_chunk_to_wav (AVSpeechSynthesizer *synth,
                    AVSpeechUtterance *utterance,
                    NSURL *wav_url,
                    AVAudioFile *__strong *wav_file_io,
                    NSError *__autoreleasing *err_out)
{
  __block BOOL done = NO;
  __block NSError *local_err = nil;
  __block AVAudioFile *wav_file = *wav_file_io;

  [synth writeUtterance:utterance toBufferCallback:^(AVAudioBuffer *buffer) {
    AVAudioPCMBuffer *pcm = (AVAudioPCMBuffer *) buffer;

    if (pcm.frameLength == 0) {
      done = YES;
      return;
    }

    if (!wav_file) {
      /* WAV (PCM Linear) — streaming-friendly. AAC를 직접 누적 쓰면
       * 인코더 state가 깨져 'dta?' 에러로 파일 열 수 없음. */
      NSDictionary *settings = @{
        AVFormatIDKey            : @(kAudioFormatLinearPCM),
        AVSampleRateKey          : @(pcm.format.sampleRate),
        AVNumberOfChannelsKey    : @(pcm.format.channelCount),
        AVLinearPCMBitDepthKey   : @(32),
        AVLinearPCMIsFloatKey    : @YES,
        AVLinearPCMIsBigEndianKey: @NO,
      };
      wav_file = [[AVAudioFile alloc]
          initForWriting:wav_url
                settings:settings
            commonFormat:pcm.format.commonFormat
             interleaved:pcm.format.interleaved
                   error:&local_err];
      if (!wav_file) {
        done = YES;
        return;
      }
    }

    NSError *write_err = nil;
    if (![wav_file writeFromBuffer:pcm error:&write_err]) {
      local_err = write_err;
      done = YES;
    }
  }];

  while (!done) {
    @autoreleasepool {
      [[NSRunLoop currentRunLoop]
            runMode:NSDefaultRunLoopMode
         beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
    }
  }

  *wav_file_io = wav_file;
  if (err_out) {
    *err_out = local_err;
  }
  return local_err ? -1 : 0;
}

/* afconvert로 WAV → AAC m4a 변환. */
static int
convert_wav_to_m4a (NSString *wav_path, NSString *m4a_path)
{
  NSTask *task = [[NSTask alloc] init];
  task.launchPath = @"/usr/bin/afconvert";
  task.arguments = @[
    @"-f", @"m4af",
    @"-d", @"aac",
    wav_path,
    m4a_path,
  ];
  task.standardOutput = [NSPipe pipe];
  task.standardError = [NSPipe pipe];

  NSError *err = nil;
  if (![task launchAndReturnError:&err]) {
    fprintf (stderr, "afconvert launch failed: %s\n",
        [err.localizedDescription UTF8String]);
    return -1;
  }
  [task waitUntilExit];
  if (task.terminationStatus != 0) {
    fprintf (stderr, "afconvert failed with exit %d\n", task.terminationStatus);
    return -1;
  }
  return 0;
}

int
main (int argc, const char *argv[])
{
  @autoreleasepool {
    NSString *out_path = nil;
    float rate = 0.5f;
    float pitch = 1.0f;
    float volume = 1.0f;
    NSString *voice_id = nil;

    for (int i = 1; i < argc; ++i) {
      NSString *arg = @(argv[i]);
      if (([arg isEqualToString:@"--out"]) && i + 1 < argc) {
        out_path = @(argv[++i]);
      } else if (([arg isEqualToString:@"--rate"]) && i + 1 < argc) {
        rate = (float) atof (argv[++i]);
      } else if (([arg isEqualToString:@"--pitch"]) && i + 1 < argc) {
        pitch = (float) atof (argv[++i]);
      } else if (([arg isEqualToString:@"--volume"]) && i + 1 < argc) {
        volume = (float) atof (argv[++i]);
      } else if (([arg isEqualToString:@"--voice"]) && i + 1 < argc) {
        voice_id = @(argv[++i]);
      } else if ([arg isEqualToString:@"--list-voices"]) {
        return list_voices ();
      } else if ([arg isEqualToString:@"-h"] || [arg isEqualToString:@"--help"]) {
        print_usage (argv[0]);
        return 0;
      } else {
        fprintf (stderr, "Unknown argument: %s\n", argv[i]);
        print_usage (argv[0]);
        return 1;
      }
    }

    if (!out_path) {
      fprintf (stderr, "Error: --out is required\n");
      print_usage (argv[0]);
      return 1;
    }

    NSString *text = read_stdin_utf8 ();
    if (!text || text.length == 0) {
      fprintf (stderr, "Error: empty text on stdin\n");
      return 1;
    }

    NSArray<NSString *> *chunks = split_into_chunks (text);
    if (chunks.count == 0) {
      fprintf (stderr, "Error: no non-empty lines in input\n");
      return 1;
    }

    AVSpeechSynthesisVoice *voice = nil;
    if (voice_id) {
      voice = [AVSpeechSynthesisVoice voiceWithIdentifier:voice_id];
      if (!voice) {
        voice = [AVSpeechSynthesisVoice voiceWithLanguage:voice_id];
      }
      if (!voice) {
        fprintf (stderr, "Warning: voice '%s' not found, using default\n",
            [voice_id UTF8String]);
      }
    }

    NSURL *out_url = [NSURL fileURLWithPath:out_path];
    [[NSFileManager defaultManager] removeItemAtURL:out_url error:nil];

    /* 임시 WAV 파일 (PCM raw) — 누적 쓰기에 안전한 포맷 */
    NSString *wav_path = [NSString stringWithFormat:@"%@.tmp.wav", out_path];
    NSURL *wav_url = [NSURL fileURLWithPath:wav_path];
    [[NSFileManager defaultManager] removeItemAtURL:wav_url error:nil];

    AVSpeechSynthesizer *synth = [[AVSpeechSynthesizer alloc] init];
    AVAudioFile *wav_file = nil;

    int total = (int) chunks.count;
    fprintf (stderr,
        "Encoding %d chunk(s) → %s (rate=%.2f pitch=%.2f volume=%.2f voice=%s)\n",
        total, [out_path UTF8String], rate, pitch, volume,
        voice_id ? [voice_id UTF8String] : "(default)");

    int done_count = 0;
    for (NSString *chunk in chunks) {
      AVSpeechUtterance *u = make_utterance (chunk, rate, pitch, volume, voice);
      NSError *err = nil;
      if (speak_chunk_to_wav (synth, u, wav_url, &wav_file, &err) != 0) {
        fprintf (stderr, "Error on chunk %d/%d: %s\n",
            done_count + 1, total,
            [err.localizedDescription UTF8String]);
        return 1;
      }
      done_count++;
      if (done_count % 10 == 0 || done_count == total) {
        fprintf (stderr, "  ... %d/%d chunks\n", done_count, total);
      }
    }

    wav_file = nil;  /* ARC가 close + flush. WAV는 close 시 헤더가 안전히 갱신됨. */

    fprintf (stderr, "Converting WAV → m4a (AAC) ...\n");
    if (convert_wav_to_m4a (wav_path, out_path) != 0) {
      return 1;
    }
    [[NSFileManager defaultManager] removeItemAtPath:wav_path error:nil];

    fprintf (stderr, "Saved: %s\n", [out_path UTF8String]);
    return 0;
  }
}
