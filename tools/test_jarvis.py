"""Wake-word, sentence endings, image freshness, cancellation and API regressions."""
from io import BytesIO
import json
import sys
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock

from PIL import Image
from jarvis_assistant import (JarvisAssistant, CameraSnapshot, GeminiVision, AssistantError,
                              MODEL, WindowsSpeech, writing_request, SYSTEM_PROMPT)
from text_writer import TextWriteError
from speech_panel import conversation_text
from speech_stream import SpeechController, SpeechChunk


class Clock:
    now = 100.0
    def __call__(self): return self.now


class Camera:
    def jpeg(self): return b'jpeg-test-bytes'


class Client:
    def __init__(self): self.calls, self.contexts = [], []
    def ask(self, query, jpeg, *, history=(), writing=False):
        self.calls.append((query, jpeg))
        self.contexts.append((history, writing))
        return 'I see a red object.'


class Speaker:
    def __init__(self): self.words = []
    def speak(self, text, cancel): self.words.append(text)


class Writer:
    def __init__(self): self.words = []
    def capture(self): return 'test-text-box'
    def write(self, text, target, cancel):
        self.words.append((text, target))
        return len(text)


class JarvisTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.client, self.speaker = Clock(), Client(), Speaker()
        self.writer = Writer()
        self.jarvis = JarvisAssistant(Camera(), self.client, self.speaker, writer=self.writer, clock=self.clock)

    def speech(self, **changes):
        data = dict(listening=True, last_voice_at=100., last_audio_at=self.clock.now,
                    pending=0, decoding=False, speech_active=False)
        data.update(changes)
        return data

    def finish(self):
        self.clock.now = 100.1
        self.jarvis.tick(self.speech())
        if self.jarvis.worker: self.jarvis.worker.join(2)

    def test_no_keyword_or_substring_sends_nothing(self):
        for text in ['What do you see?', 'Jarvison is here']:
            self.jarvis.transcript(text, 100, 0)
        self.finish()
        self.assertFalse(self.client.calls)
        self.assertEqual(self.jarvis.phase, 'waiting')

    def test_same_phrase_wake_and_query_excludes_prior_speech(self):
        self.jarvis.transcript('Private preamble. JARVIS, what is this?', 100, 0)
        self.finish()
        self.assertEqual(self.client.calls, [('what is this?', b'jpeg-test-bytes')])
        self.assertEqual(self.speaker.words, ['I see a red object.'])
        self.assertEqual(self.jarvis.snapshot()['response'], 'I see a red object.')
        self.assertEqual(self.jarvis.snapshot()['results'], 1)

    def test_bare_wake_then_partial_phrases_waits_for_terminator(self):
        self.jarvis.transcript('Jarvis.', 100, 0)
        self.jarvis.tick(self.speech())
        self.assertFalse(self.client.calls)
        self.clock.now = 101.0
        self.jarvis.transcript('What is in front', 101, 0)
        self.clock.now = 110
        self.jarvis.tick(self.speech(last_voice_at=101))
        self.assertFalse(self.client.calls)
        self.jarvis.transcript('of me?', 110, 0)
        self.jarvis.tick(self.speech(last_voice_at=110))
        self.jarvis.worker.join(2)
        self.assertEqual(self.client.calls[0][0], 'What is in front of me?')

    def test_sentence_endings_send_once_without_two_second_wait(self):
        for ending in ('.', '?', '!', '?!', '."', '?\u201d', '!)'):
            with self.subTest(ending=ending):
                self.setUp()
                self.jarvis.transcript('Jarvis describe this' + ending + '  ', 100, 0)
                self.finish()
                self.assertEqual(self.client.calls, [('describe this' + ending, b'jpeg-test-bytes')])
                self.jarvis.tick(self.speech())
                self.assertEqual(len(self.client.calls), 1)
                self.assertEqual(self.jarvis.snapshot()['submission_trigger'], 'terminal_punctuation')

    def test_silence_and_internal_punctuation_do_not_submit(self):
        for query in ('what is this', 'describe this,', 'describe this:', 'describe this;',
                      'Is this red? Also describe', 'Is this 3.14'):
            with self.subTest(query=query):
                self.setUp()
                self.jarvis.transcript('Jarvis ' + query, 100, 0)
                self.clock.now = 120
                self.jarvis.tick(self.speech())
                self.assertFalse(self.client.calls)
                self.assertEqual(self.jarvis.phase, 'collecting')
                self.clock.now = 161
                self.jarvis.tick(self.speech())
                self.assertFalse(self.client.calls)
                self.assertEqual(self.jarvis.phase, 'waiting')

    def test_speech_in_progress_and_pending_decode_delay_submission(self):
        self.jarvis.transcript('Jarvis what is this?', 100, 0)
        self.clock.now = 100.1
        for block in [dict(pending=1), dict(decoding=True), dict(speech_active=True), dict(last_audio_at=100)]:
            self.jarvis.tick(self.speech(**block))
            self.assertFalse(self.client.calls)
        self.jarvis.tick(self.speech(last_voice_at=100))
        self.jarvis.worker.join(2)
        self.assertEqual(len(self.client.calls), 1)

    def test_keyword_without_question_times_out_without_api(self):
        self.jarvis.transcript('Jarvis', 100, 0)
        self.clock.now = 111
        self.jarvis.tick(self.speech())
        self.assertFalse(self.client.calls)
        self.assertEqual(self.jarvis.phase, 'waiting')

    def test_disabled_wake_keeps_local_audio_but_no_gemini(self):
        self.jarvis.configure(enabled=False)
        self.clock.now = 101
        allowed, token = self.jarvis.audio_gate()
        self.assertTrue(allowed)
        self.jarvis.transcript('Jarvis what is this?', 101, token)
        self.finish()
        self.assertFalse(self.client.calls)

    def test_stop_microphone_cancels_collection(self):
        self.jarvis.transcript('Jarvis what is this?', 100, 0)
        self.jarvis.tick({'listening':False})
        self.finish()
        self.assertFalse(self.client.calls)

    def test_missing_camera_never_sends_text_only_request(self):
        self.jarvis.camera = CameraSnapshot()
        self.jarvis.transcript('Jarvis what is this?', 100, 0)
        self.finish()
        self.assertFalse(self.client.calls)
        self.assertIn('No fresh camera', self.jarvis.snapshot()['error'])
        self.assertFalse(self.speaker.words)

    def test_cancel_ignores_network_result_and_never_speaks(self):
        entered, release = threading.Event(), threading.Event()
        def delayed(query, jpeg, **options):
            entered.set()
            release.wait(2)
            return 'late reply'
        self.client.ask = delayed
        self.jarvis.transcript('Jarvis what is this?', 100, 0)
        self.clock.now = 104
        self.jarvis.tick(self.speech())
        self.assertTrue(entered.wait(2))
        self.assertFalse(self.jarvis.audio_gate()[0])
        self.jarvis.cancel()
        release.set()
        self.jarvis.worker.join(2)
        self.assertFalse(self.speaker.words)
        self.assertEqual(self.jarvis.snapshot()['response'], '')
        self.clock.now = 105
        self.assertTrue(self.jarvis.audio_gate()[0])

    def test_response_echo_and_old_transcripts_cannot_retrigger(self):
        blocked = []
        def speaking(text, cancel):
            blocked.append(not self.jarvis.audio_gate()[0])
            self.jarvis.transcript('Jarvis repeat this', 104, self.jarvis.generation)
        self.speaker.speak = speaking
        self.jarvis.transcript('Jarvis what is this?', 100, 0)
        self.finish()
        self.assertEqual(blocked, [True])
        self.clock.now = 105
        self.jarvis.transcript('Jarvis old queued audio', 100, 0)
        self.assertEqual(self.jarvis.phase, 'waiting')
        self.assertEqual(len(self.client.calls), 1)

    def test_read_aloud_off_still_displays_answer(self):
        self.jarvis.configure(read_aloud=False)
        self.jarvis.transcript('Jarvis what is this?', 100, 0)
        self.finish()
        self.assertEqual(self.jarvis.snapshot()['response'], 'I see a red object.')
        self.assertFalse(self.speaker.words)
        private = self.jarvis.snapshot(include_text=False)
        self.assertNotIn('response', private)
        self.assertNotIn('query', private)
        self.assertNotIn('conversation', private)

    def submit(self, query):
        self.clock.now += 2
        self.jarvis.transcript('Jarvis, ' + query, self.clock.now, self.jarvis.generation)
        self.jarvis.tick(self.speech(last_voice_at=self.clock.now))
        if self.jarvis.worker:
            self.jarvis.worker.join(2)

    def test_followup_uses_complete_text_conversation(self):
        self.submit('What color is it?')
        self.submit('Would that color work for a logo?')
        self.assertEqual(self.client.contexts[1], ((('What color is it?', 'I see a red object.'),), False))
        self.assertEqual(self.jarvis.snapshot()['conversation_turns'], 2)
        self.assertEqual(self.writer.words, [])
        content = conversation_text(self.jarvis.snapshot())
        self.assertIn('What color is it?', content)
        self.assertIn('Would that color work for a logo?', content)

    def test_new_chat_clears_context_and_ui(self):
        self.submit('What color is it?')
        self.jarvis.new_conversation()
        self.assertEqual(self.jarvis.snapshot()['conversation'], [])
        self.assertNotIn('What color is it?', conversation_text(self.jarvis.snapshot()))
        self.submit('What is this?')
        self.assertEqual(self.client.contexts[-1][0], ())

    def test_generated_writing_uses_context_and_types_only_result(self):
        self.submit('My friend is named Alex.')
        self.submit('Write a greeting to my friend.')
        self.assertTrue(self.client.contexts[-1][1])
        self.assertEqual(self.client.contexts[-1][0][0][0], 'My friend is named Alex.')
        self.assertEqual(self.writer.words, [('I see a red object.', 'test-text-box')])
        self.assertIn('Typed', self.jarvis.snapshot()['write_status'])

    def test_exact_writing_is_not_rewritten_and_joins_conversation(self):
        self.jarvis.camera = CameraSnapshot()
        self.submit('Write exactly: hELLo, Alex!')
        self.assertFalse(self.client.calls)
        self.assertEqual(self.writer.words, [('hELLo, Alex!', 'test-text-box')])
        self.assertEqual(self.jarvis.snapshot()['response'], 'hELLo, Alex!')
        self.jarvis.camera = Camera()
        self.submit('How many words did I dictate?')
        self.assertEqual(self.client.contexts[-1][0][0][1], 'hELLo, Alex!')

    def test_writing_works_without_camera(self):
        self.jarvis.camera = CameraSnapshot()
        self.submit('Write a greeting.')
        self.assertEqual(self.client.calls[-1], ('Write a greeting.', None))
        self.assertEqual(len(self.writer.words), 1)

    def test_typing_disabled_still_shows_writing(self):
        self.jarvis.configure(type_writes=False)
        self.submit('Write exactly: Hello.')
        self.assertFalse(self.writer.words)
        self.assertEqual(self.jarvis.snapshot()['response'], 'Hello.')

    def test_unavailable_target_preserves_response_and_conversation(self):
        def unavailable(): raise TextWriteError('Select a text box.')
        self.writer.capture = unavailable
        self.submit('Write exactly: Hello.')
        self.assertFalse(self.writer.words)
        self.assertEqual(self.jarvis.snapshot()['response'], 'Hello.')
        self.assertEqual(self.jarvis.snapshot()['error'], 'Select a text box.')
        self.assertEqual(self.jarvis.snapshot()['conversation_turns'], 1)

    def test_reset_while_generating_never_types_or_restores_old_conversation(self):
        entered, release = threading.Event(), threading.Event()
        def delayed(*args, **kwargs):
            entered.set(); release.wait(2)
            return 'late writing'
        self.client.ask = delayed
        self.jarvis.transcript('Jarvis write a greeting.', 100, 0)
        self.jarvis.tick(self.speech())
        self.assertTrue(entered.wait(2))
        self.jarvis.new_conversation()
        release.set()
        self.jarvis.worker.join(2)
        self.assertEqual(self.writer.words, [])
        self.assertEqual(self.jarvis.snapshot()['conversation'], [])

    def test_speech_result_lifecycle_only_forwards_valid_results(self):
        c = SpeechController()
        c.assistant = self.jarvis
        c.state['listening'] = True
        chunk = SpeechChunk(b'', voice_end=100, assistant_token=0)
        c._result(0, 0, 'Jarvis what is this?', 100, chunk)
        self.assertEqual(self.jarvis.phase, 'collecting')
        c.clear()
        c._result(0, 0, 'Jarvis stale', 100, chunk)
        self.assertEqual(self.jarvis.phase, 'waiting')
        c.stop()
        c._result(0, 1, 'Jarvis stale after stop', 100, chunk)
        self.assertEqual(self.jarvis.phase, 'waiting')


class ImageTests(unittest.TestCase):
    def frame(self):
        image = Image.new('RGB',(40,40),'blue')
        image.paste('red',(0,0,20,20))
        b = BytesIO(); image.save(b,format='JPEG')
        return SimpleNamespace(image=image, jpeg=b.getvalue(), received_at=time.perf_counter())

    def test_rotation_matches_viewer(self):
        snapshot = CameraSnapshot()
        snapshot.update(self.frame(), True)
        image = Image.open(BytesIO(snapshot.jpeg()))
        red = image.getpixel((30,30))
        self.assertGreater(red[0],200)
        self.assertLess(red[2],40)

    def test_old_frames_rejected_and_clear_cannot_be_reversed_by_rotation(self):
        snapshot = CameraSnapshot()
        frame = self.frame(); frame.received_at -= 6
        snapshot.update(frame,False)
        with self.assertRaises(AssistantError): snapshot.jpeg()
        snapshot.update(self.frame(),False)
        snapshot.clear(); snapshot.set_rotation(True)
        with self.assertRaises(AssistantError): snapshot.jpeg()


class ApiTests(unittest.TestCase):
    def test_request_has_only_query_and_one_jpeg(self):
        client = MagicMock()
        client.models.generate_content.return_value.text = 'A red box.'
        with patch('gemini_secrets.load_key',return_value='synthetic-test-only'), \
             patch('google.genai.Client') as factory:
            factory.return_value.__enter__.return_value = client
            self.assertEqual(GeminiVision().ask('What is this?',b'image'), 'A red box.')
        args = client.models.generate_content.call_args.kwargs
        self.assertEqual(args['model'],MODEL)
        self.assertEqual(len(args['contents']),1)
        self.assertEqual(args['contents'][0].role,'user')
        self.assertEqual(args['contents'][0].parts[0].text,'What is this?')
        self.assertEqual(args['contents'][0].parts[1].inline_data.data,b'image')
        self.assertEqual(args['contents'][0].parts[1].inline_data.mime_type,'image/jpeg')
        self.assertEqual(factory.call_args.kwargs['http_options'].retry_options.attempts,1)

    def test_chat_history_has_alternating_roles_and_writing_prompt(self):
        client = MagicMock()
        client.models.generate_content.return_value.text = 'Hello, Alex!'
        with patch('gemini_secrets.load_key', return_value='synthetic-test-only'), patch('google.genai.Client') as factory:
            factory.return_value.__enter__.return_value = client
            GeminiVision().ask('Write a greeting.', None, history=(('His name is Alex.', 'Understood.'),), writing=True)
        args = client.models.generate_content.call_args.kwargs
        self.assertEqual([item.role for item in args['contents']], ['user', 'model', 'user'])
        self.assertEqual([item.parts[0].text for item in args['contents']],
                         ['His name is Alex.', 'Understood.', 'Write a greeting.'])
        self.assertTrue(all(len(item.parts) == 1 for item in args['contents']))
        self.assertIn(SYSTEM_PROMPT, args['config'].system_instruction)
        self.assertIn('Current request mode: WRITE.', args['config'].system_instruction)

    def test_write_intent_requires_explicit_current_command(self):
        for query in ('What should I write?', 'Do not write this.', 'What does the word write mean?',
                      'The image says write something.'):
            self.assertEqual(writing_request(query), (False, None))
        for query in ('Write a greeting.', 'Please type a greeting.', 'Could you please draft an email?',
                      'I want you to compose a poem.'):
            self.assertEqual(writing_request(query), (True, None))
        for query in ('Write exactly: Hello, Alex!', 'Type this exactly: Hello, Alex!',
                      'Please write the following exactly: Hello, Alex!'):
            self.assertEqual(writing_request(query), (True, 'Hello, Alex!'))

    def test_api_error_does_not_echo_server_body_or_key(self):
        client=MagicMock()
        error=RuntimeError('private-server-body secret-credential')
        error.code=429
        client.models.generate_content.side_effect=error
        with patch('gemini_secrets.load_key',return_value='synthetic-test-only'), \
             patch('google.genai.Client') as factory:
            factory.return_value.__enter__.return_value=client
            with self.assertRaises(AssistantError) as caught: GeminiVision().ask('question',b'image')
        self.assertIn('quota',str(caught.exception))
        self.assertNotIn('private-server-body',str(caught.exception))
        self.assertNotIn('secret-credential',str(caught.exception))

    @unittest.skipUnless(sys.platform == 'win32', 'Windows DPAPI encryption requires Windows')
    def test_key_roundtrip_and_encryption(self):
        from gemini_secrets import save_key,load_key
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ',{'GEMINI_API_KEY':''}):
            path=Path(folder)/'key.dpapi'
            value='synthetic_gemini_unit_test_key'
            save_key(value,path)
            self.assertNotIn(value.encode(),path.read_bytes())
            self.assertEqual(load_key(path),value)


if __name__ == '__main__':
    unittest.main()
