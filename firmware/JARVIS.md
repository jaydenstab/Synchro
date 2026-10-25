# Jarvis camera assistant

Run commands from the project root unless a section says otherwise.

Say **“Jarvis, what do you see?”**. When the recognized request ends with a
**period, question mark or exclamation mark**, the app sends it and one fresh camera JPEG to Google's
Gemini API, displays the answer in the **Jarvis conversation** tab and reads it
aloud using the computer's Windows voice when **Read aloud** is checked.

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
180-degree rotation setting. A disconnected/stopped camera is omitted instead of
sending an old frame. All requests still reach Gemini; the prompt tells it not to
invent visual details when there is no image.

The microphone starts off in a normal launch. Listen for Jarvis, Read aloud,
and Typing & keys are checked by default. To use local dictation only,
uncheck Listen for Jarvis before starting the microphone. In Mac `--preview`,
these actions are disabled and no cloud request, playback, or typing occurs.

## Typing and keyboard actions in the selected text box

Click a writable text box in another app before speaking, then leave it focused:

- **“Jarvis, write a greeting.”** generates a general greeting and types only
  the generated text, without a preamble or extra quotation marks.
- **“Jarvis, write exactly: Hello, Alex!”** asks Gemini to preserve `Hello, Alex!`
  exactly. Exact dictation also goes through Gemini. Recognition and the model
  can make mistakes; check the transcript and generated text.
- **“Jarvis, write a shorter version.”** uses the preceding conversation as context.
  Questions such as “What should I write?” only receive an answer and are not typed.
- **“Jarvis, type a generic search query and then press Enter.”** generates the
  query, types it and presses Enter, in that order.
- **“Jarvis, select all and then copy.”** runs Ctrl+A followed by Ctrl+C.
- **“Jarvis, press Enter.”** produces a single Enter action.

The system prompt is `SYSTEM_PROMPT` in tools/jarvis_assistant.py. Every Jarvis
request goes to Gemini; there is no local command parser or exact-dictation bypass.
Gemini returns schema-constrained JSON with a `reply` and ordered `actions`, e.g.:

```json
{"reply":"","actions":[{"type":"text","value":"weather forecast"},{"type":"key","value":"enter"}]}
```

Only validated `text` and `key` actions execute. Reply prose and literal text
values are never parsed for commands. The entire plan is validated before any
input: maximum 12 actions and 12,000 typed characters. Unsupported keys, malformed
JSON, extra fields and invalid text reject the whole plan. The prompt limits
actions to explicit requests in the current turn; quoted text, camera text and
conversation history are not permission to act. Intent interpretation is performed
by Gemini, so it can still misunderstand a spoken request.

The app captures the focused field before asking Gemini, then checks that the
same field is still focused before each character and key action. Text is sent one
Unicode character at a time, with a 12 ms pacing interval and complete press/release
pairs. Key chords release modifiers in reverse order. Actions have an 80 ms gap.
Focus changes, cancellations or failed input stop the rest of the sequence without
retrying. A Tab or Enter that changes the focused field prevents later actions from
running in a different field. Partial output stays in place; UI status reports how
many actions completed. The app does not activate windows or choose another field.

Text inserts at the caret or replaces the selection. **Enter has its normal effect,
including submitting searches/messages** when requested. Supported keys are Enter,
Shift+Enter, Tab, Shift+Tab, Backspace, Delete, Escape, arrows, Home, End, Page Up/Down;
Ctrl+A/C/V/X/Z/Y/B/I/U and Ctrl+Shift+Z. Clipboard shortcuts behave normally;
plain typing never replaces or reads the clipboard. Arbitrary code, shell commands,
window switching and unsupported shortcuts are not action types.
Password/read-only fields and terminal command inputs are not supported. Some
custom editors may not expose a writable field through Windows accessibility.

All successful questions, generated writing and exact dictation are shown in the
same conversation. **New chat** clears that context and cancels any pending reply.
History is kept in memory until New chat or app shutdown; it is not saved to disk.

## Controls

- **Listen for Jarvis** enables/disables cloud requests; local transcription
  continues when it is unchecked.
- **Read aloud** enables Windows text-to-speech. The reply remains visible.
- **Typing & keys** enables/disables all text and key actions in the selected field.
  Turning it off still sends requests to Gemini and displays the planned actions.
- **Stop reply** cancels collection, pending actions or playback. An API request already
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
The saved key file is excluded from Git and source packages; each Windows user
configures their own key. The key-entry utility uses Windows DPAPI and does not
work in the Mac preview.
Logs and the local status endpoint exclude questions, replies, API keys and raw
server error bodies. Requests, JPEGs and responses are held in memory; the
activated request text (including exact dictation), previous conversation text and
current image when available are transmitted to Google. Model plans can insert
text and press the supported keys when Typing & keys is on. New chat clears
conversation history.

With the project .venv installed and camera configuration saved (see README):

```powershell
.\tools\Start-Bluetooth-Camera.ps1 -Listen -PausePointer
```

On another Windows computer, use the portable Python command in README.md,
adding `--listen --pause-pointer` for voice tests. Camera questions need a powered,
paired camera connected to the viewer; text/key requests do not. Gemini requires
internet and a valid key.

## Verification and historical observations

The current software checks exercise fixtures and stubbed cloud/OS calls; they
do not establish recognition accuracy, Windows rendering, or compatibility with
every target application's text fields. Windows DPAPI and native INPUT layout
checks require Windows and are skipped on a Mac. Use the root README's test and
acceptance steps for the current source.

Earlier hardware-branch checks covered wake gating, terminal punctuation without a
two-second wait, partial phrases, punctuation inside a sentence, pending
transcription, stale/missing images, rotation, cancellation, TTS echo exclusion
and sanitized API errors. Writing tests cover exact text, conversation context,
New chat, cancellation, focus changes, Unicode packets and blocked inputs; native
typing uses a stubbed input function in tests. The following live checks are
historical owner-machine observations from the hardware branch, not a rerun
of the redesigned app. A real Gemini check generated
“Hey Alex, great to see you!” and answered “Alex” on the follow-up asking the
friend's name. Before the punctuation update, synthetic spoken
“Jarvis, what color is the rectangle?” passed through the real Silero, Parakeet,
Gemini and Windows TTS pipeline; Gemini correctly answered “The rectangle is
red.” The real camera separately reconnected at 640×480 in the viewer.

On 25 October 2026, a live laptop-microphone dictation command also inserted
12 characters into a focused Notepad document. The application reported the
insertion, the text was observed in Notepad, and the user confirmed it appeared.
This verifies the live typing path, not general transcription accuracy.

The ordered-action update was checked against the real Gemini API with Enter,
generated search text followed by Enter, Ctrl+A then Ctrl+C, the reported
Kirkland phrase, a shortcut explanation and literal dictation of "press Enter".
All six returned the expected plans. Those API checks did not send desktop input.
Sequence/cancellation/focus and native key packet regression tests use fake input.
The compound voice-to-desktop path still needs a live test in a selected test field.

References: [Gemini keys](https://ai.google.dev/gemini-api/docs/api-key),
[image understanding](https://ai.google.dev/gemini-api/docs/image-understanding),
[structured output](https://ai.google.dev/gemini-api/docs/structured-output),
[Google Gen AI SDK](https://googleapis.github.io/python-genai/).
