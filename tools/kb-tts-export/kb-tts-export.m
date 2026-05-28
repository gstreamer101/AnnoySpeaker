/* kb-tts-export: Synthesize stdin text to an .m4a file via AVSpeechSynthesizer.
 *
 * Mirrors the options exposed by the macttssink GStreamer plugin so the GUI
 * can pass the same rate/pitch/volume/voice settings used for live playback.
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
      "                           \"com.apple.voice.compact.ko-KR.Yuna\"\n",
      prog);
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

    AVSpeechUtterance *utterance =
        [AVSpeechUtterance speechUtteranceWithString:text];
    utterance.rate = rate;
    utterance.pitchMultiplier = pitch;
    utterance.volume = volume;
    /* 한국어 마지막 음절 잘림 방지 (macttssink와 동일한 마진) */
    utterance.postUtteranceDelay = 0.25;

    if (voice_id) {
      AVSpeechSynthesisVoice *voice =
          [AVSpeechSynthesisVoice voiceWithIdentifier:voice_id];
      if (!voice) {
        voice = [AVSpeechSynthesisVoice voiceWithLanguage:voice_id];
      }
      if (voice) {
        utterance.voice = voice;
      } else {
        fprintf (stderr, "Warning: voice '%s' not found, using default\n",
            [voice_id UTF8String]);
      }
    }

    NSURL *out_url = [NSURL fileURLWithPath:out_path];
    /* 기존 파일이 있으면 덮어쓰기 */
    [[NSFileManager defaultManager] removeItemAtURL:out_url error:nil];

    __block AVAudioFile *audio_file = nil;
    __block NSError *file_error = nil;
    __block BOOL done = NO;

    AVSpeechSynthesizer *synth = [[AVSpeechSynthesizer alloc] init];

    [synth writeUtterance:utterance toBufferCallback:^(AVAudioBuffer *buffer) {
      AVAudioPCMBuffer *pcm = (AVAudioPCMBuffer *) buffer;

      if (pcm.frameLength == 0) {
        /* EOS — 마지막 빈 버퍼가 종료 신호 */
        done = YES;
        return;
      }

      if (!audio_file) {
        /* 첫 버퍼에서 포맷을 알 수 있어 그때 파일 생성 */
        NSDictionary *settings = @{
          AVFormatIDKey            : @(kAudioFormatMPEG4AAC),
          AVSampleRateKey          : @(pcm.format.sampleRate),
          AVNumberOfChannelsKey    : @(pcm.format.channelCount),
          AVEncoderAudioQualityKey : @(AVAudioQualityHigh),
        };
        audio_file = [[AVAudioFile alloc]
            initForWriting:out_url
                  settings:settings
              commonFormat:pcm.format.commonFormat
               interleaved:pcm.format.interleaved
                     error:&file_error];
        if (!audio_file) {
          done = YES;
          return;
        }
      }

      NSError *write_err = nil;
      if (![audio_file writeFromBuffer:pcm error:&write_err]) {
        file_error = write_err;
        done = YES;
      }
    }];

    /* AVSpeechSynthesizer는 main thread의 NSRunLoop를 통해 콜백을 전달하므로
     * dispatch_semaphore_wait로 block하면 콜백이 영원히 안 옴. RunLoop를
     * 짧은 단위로 돌리면서 done flag를 폴링한다. */
    while (!done) {
      @autoreleasepool {
        [[NSRunLoop currentRunLoop]
              runMode:NSDefaultRunLoopMode
            beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
      }
    }

    /* ARC가 audio_file을 nil 처리하면 자동 close + flush */
    audio_file = nil;

    if (file_error) {
      fprintf (stderr, "Error writing audio file: %s\n",
          [file_error.localizedDescription UTF8String]);
      return 1;
    }

    fprintf (stderr,
        "Saved: %s (rate=%.2f pitch=%.2f volume=%.2f voice=%s)\n",
        [out_path UTF8String], rate, pitch, volume,
        voice_id ? [voice_id UTF8String] : "(default)");
    return 0;
  }
}
