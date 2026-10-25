# Start in macOS Terminal

```bash
# Extract this kit and navigate into the extracted folder:
cd /path/to/visionglove-codex-kit

# Check baseline before asking Codex to edit anything:
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q

# In one terminal, run baseline app:
python -m uvicorn app:app --reload
# Visit http://127.0.0.1:8000

# In another terminal, from this same folder, launch your local coding agent:
codex --oss --local-provider ollama -m gpt-oss:20b
# Paste contents of CODEX_START_HERE.md into Codex.
# AGENTS.md in project root gives persistent conventions.
```

Alternative: `ollama launch codex` can launch/configure Codex; verify it uses your desired model.

If your Mac struggles with memory, keep tasks small and adjust context size according to local RAM and Ollama configuration. The model is a *coding assistant*, not your real-time IMU classifier.

When a stage is done, use the next prompt from NEXT_PROMPTS.md and inspect working code and actual test results before proceeding.
