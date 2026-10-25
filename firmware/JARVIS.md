# Jarvis camera assistant

Say **“Jarvis, what do you see?”**. When the recognized request ends with a
**period, question mark or exclamation mark**, the app sends it and one fresh camera JPEG to Google's
Gemini API, displays the answer in the **Jarvis conversation** tab and reads it
aloud using the computer's Windows voice.

The laptop microphone, local Parakeet TDT 0.6B v2 and Silero VAD remain in use.
Parakeet decodes speech at short local pauses. Only text after the recognized
whole word “Jarvis” is collected for a Gemini request. Keyword and question
may be in the same phrase, or the question may follow shortly afterward.
Silero still uses a short pause (about 512 ms) to produce a local transcription.
Once transcription finishes, a final `.`, `?` or `!` triggers submission without
an extra two-second delay. Closing quotes or brackets after that punctuation
are accepted. Punctuation inside a sentence does not trigger submission.
Recognition supplies punctuation; you do not need to say “question mark”.
If the transcript has no terminating punctuation, Jarvis keeps collecting the
next phrase. Silence alone does not submit it, and the sixty-second collection
timeout cancels it. Unfinished or queued transcriptions and active speech must
finish before submission. A punctuated wake word alone never sends a request.

The current model is `gemini-3.5-flash-lite`. Questions and answers belong to one
conversation for the current app session. Each Gemini request includes previous
successful text turns and the new question, plus the current JPEG when available.
Previous images are not retained in the conversation. Raw microphone audio is not sent.
The camera frame must be at most five seconds old and follows the viewer's
180-degree rotation setting. A disconnected/stopped camera produces a visible
error for ordinary camera questions instead of sending an old frame. General
writing requests can run without a camera image.

## Writing into the selected text box

Click a writable text box in another app before speaking, then leave it focused:

- **“Jarvis, write a greeting.”** generates a general greeting and types only
  the generated text, without a preamble or extra quotation marks.
- **“Jarvis, write exactly: Hello, Alex!”** inserts `Hello, Alex!` directly from
  the recognized transcript. Exact mode bypasses rewriting by Gemini. Recognition
  can still change spoken capitalization/punctuation or mishear words; check the transcript.
- **“Jarvis, write a shorter version.”** uses the preceding conversation as context.
  Questions such as “What should I write?” only receive an answer and are not typed.

The system prompt is `SYSTEM_PROMPT` in tools/jarvis_assistant.py. Explicit
write/type/draft/compose commands choose writing mode locally. Camera text and
ordinary model answers cannot activate typing. The app captures the focused field
when a writing request is submitted and checks that the same field remains focused
before each batch of Unicode characters. If focus changes, typing stops and the
response remains visible. Text inserts at the caret or replaces the current selection.
It never presses Enter to submit, sends a message, or uses the clipboard.
Password/read-only fields and terminal command inputs are not supported. Some
custom editors may not expose a writable field through Windows accessibility.

All successful questions, generated writing and exact dictation are shown in the
same conversation. **New chat** clears that context and cancels any pending reply.
History is kept in memory until New chat or app shutdown; it is not saved to disk.

## Controls

- **Listen for Jarvis** enables/disables cloud requests; local transcription
  continues when it is unchecked.
- **Read aloud** enables Windows text-to-speech. The reply remains visible.
- **Type writing requests** enables/disables insertion into the selected text box.
  Turning it off still generates and displays writing.
- **Stop reply** cancels collection or stops playback. An API request already
  sent may finish, but its cancelled result is discarded.
- **Stop mic**, **Clear text**, and closing the viewer also cancel pending replies.
  Clear text clears the local transcript, while New chat clears the conversation.
- Microphone processing pauses while Gemini responds and while its answer is
  spoken, with an 800 ms cooldown to avoid feedback retriggers. New requests
  during that interval are ignored; use Stop reply to interrupt.
- A bare wake word times out after ten seconds without a question. A collected
  request times out after sixty seconds. Audio gaps and dropped transcripts
  cancel it rather than sending a partial request.
- Voice-test launches pause cursor control and select **Speech & Jarvis**.
  The **Glove** tab stays visible beside it. Use **Pause pointer**
  to stop the pointer. Esc stops in-progress typing only; it does not stop pointer
  control, the microphone or spoken replies.

## Setup

Install requirements.txt, then configure a key on the receiving Windows computer:

```powershell
.\.venv\Scripts\python.exe tools\gemini_secrets.py
```

The hidden prompt saves a Windows-user-encrypted key in Git-ignored
`.local/gemini-api-key.dpapi`. `GEMINI_API_KEY` is an environment override.
The owner's supplied key is local and excluded from Git and share packages.
Logs and the local status endpoint exclude questions, replies, API keys and raw
server error bodies. Requests, JPEGs and responses are held in memory; the
activated request text, previous conversation text and current image are transmitted
to Google. Explicit exact dictation stays local. Writing responses may be inserted
as plain text; model responses cannot execute commands or submit messages.

With the owner's bundled Python runtime:

```powershell
.\tools\Start-Bluetooth-Camera.ps1 -Listen -PausePointer
```

On another Windows computer, use the portable Python command in README.md,
adding `--pause-pointer` for voice-only tests. The camera must be powered,
paired and connected to the viewer; Gemini requires internet.

## Verification

The full suite passes, including wake gating, terminal punctuation without a
two-second wait, partial phrases, punctuation inside a sentence, pending
transcription, stale/missing images, rotation, cancellation, TTS echo exclusion
and sanitized API errors. Writing tests cover exact text, conversation context,
New chat, cancellation, focus changes, Unicode packets and blocked inputs; native
typing uses a stubbed input function in tests. A real Gemini check generated
“Hey Alex, great to see you!” and answered “Alex” on the follow-up asking the
friend's name. Before the punctuation update, synthetic spoken
“Jarvis, what color is the rectangle?” passed through the real Silero, Parakeet,
Gemini and Windows TTS pipeline; Gemini correctly answered “The rectangle is
red.” The real camera separately reconnected at 640×480 in the viewer.

On 25 October 2026, a live laptop-microphone dictation command also inserted
12 characters into a focused Notepad document. The application reported the
insertion, the text was observed in Notepad, and the user confirmed it appeared.
This verifies the live typing path, not general transcription accuracy.

References: [Gemini keys](https://ai.google.dev/gemini-api/docs/api-key),
[image understanding](https://ai.google.dev/gemini-api/docs/image-understanding),
[Google Gen AI SDK](https://googleapis.github.io/python-genai/).
