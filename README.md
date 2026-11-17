# Local Clinical AI

A local physiotherapy correspondence prototype that turns exported notes into editable GP progress letters, discharge reports and patient follow-up email drafts.

Created by Wenjin Li. The project grew out of a WorkCover documentation experiment. The current source release focuses on clinical correspondence. Its model outputs still need clinician review, and the tested 4B configuration has not met the author's quality expectations across cases.

## Current workflow

1. Import a text-based PDF, DOCX, TXT or Markdown record.
2. Select the recognised patient/case and a correspondence type.
3. Parse note structure and select current and earlier comparison evidence where available.
4. Start a local Qwen3 model through llama.cpp to draft the clinical paragraphs.
5. Apply source-related checks and bounded rule-based edits, retaining their audit trail.
6. Review the original evidence and draft, edit, and save a text copy.

The application runs on the loopback interface with per-session authentication. The model endpoint uses a separate ephemeral key. Network inference calls target `127.0.0.1` and bypass environment proxy settings.

The source trace is a paragraph-level context aid. It does not establish that every generated claim is correct.

## Quick start

Use Python 3.11 or newer. Windows is the development target; other operating systems have not been validated for this release.

```powershell
git clone https://github.com/harry-the-dragon/local-clinical-ai.git
cd local-clinical-ai
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app\app.py --help
```

Obtain a compatible `llama-server.exe` and its companion libraries from [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases). This historical adapter uses flags including `--no-repack`, `--cache-ram`, and `--reasoning off`. Check the selected runtime's `--help` for those flags before use. New runtime versions may need adapter changes.

The existing model checksum is pinned to one Qwen3-4B-Instruct-2507 Q4_K_M artifact. The exact blob can be downloaded separately from the Ollama registry. Review the [Qwen model card and license](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) before downloading.

```powershell
New-Item -ItemType Directory -Force models | Out-Null
curl.exe -L --fail "https://registry.ollama.ai/v2/library/qwen3/blobs/sha256:85e4a5b7b8ef0e48af0e8658f5aaab9c2324c76c1641493f4d1e25fce54b18b9" -o models/qwen3-4b-instruct-2507-q4_k_m.gguf
Get-FileHash models/qwen3-4b-instruct-2507-q4_k_m.gguf -Algorithm SHA256
.venv\Scripts\python.exe app\app.py --runtime "C:\path\to\llama-server.exe" --model models\qwen3-4b-instruct-2507-q4_k_m.gguf
```

Expected SHA256 is `85e4a5b7b8ef0e48af0e8658f5aaab9c2324c76c1641493f4d1e25fce54b18b9`. The file is approximately 2.5 GB; loaded memory also depends on runtime and context settings. Model and runtime binaries are separate dependencies. Python dependency installation and model downloads use the network; document processing runs locally once dependencies are present.

Choose **Try fictional three-visit sample** first. A local browser window opens automatically. Use **Exit program** to close the app.

## Privacy and diagnostic files

**Each generation attempt saves full, unredacted local diagnostic records.** These can include the original document, extracted notes, prompts, raw model responses, rejected drafts and runtime logs. Clearing the screen leaves those files on disk.

On Windows, the default diagnostic directory is `%LOCALAPPDATA%\ClinicCorrespondence-v17-r19\diagnostics`. The directory name is historical; the backend version identifies the running code. You can select a different private state location with `--state-dir`.

Use a private, access-controlled local directory outside cloud-sync folders. Manage disk encryption, backups, access and retention through the operating system and clinic procedures. The app does not itself encrypt files at rest or delete diagnostic history on a retention schedule. Treat diagnostic ZIP exports as sensitive source records.

Only fictional text is included in this repository. Use fictional material for issues, pull requests and public demonstrations.

## Implemented scope and limits

| Area | Current source | Further work |
| --- | --- | --- |
| Input | Manual document import | Authorised Nookal API pull |
| Drafts | GP update, discharge, patient follow-up | Wider case and format coverage |
| Local model | CPU Qwen3 4B with a fixed checksum | Alternative models, context and hardware evaluation |
| Review | Source context, checks, editing and TXT export | Independent clinical validation |
| Integration | Local browser interface | Approved-content API push |
| Scheduling | User-triggered generation | Overnight batch queue and stale-source handling |

Scanned PDF OCR, universal Nookal format parsing, automatic sending, AHTR form generation and model fine-tuning are outside the current implementation. Some source inconsistencies cause rejection. Source checks and engineering tests do not establish clinical accuracy or time savings. The clinic's 8GB/i7-6700 configuration remains an unverified deployment target in the development records.

## Development checks

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The public tests cover fictional parsing and local HTTP boundaries without invoking a model. Model-in-the-loop validation remains a separate evaluation task.

## Contributing

Useful contributions include fictional counterexamples, reproducible parser failures, runtime compatibility findings and model comparisons reporting total review effort. Include the software/runtime versions, synthetic input, expected behaviour and observed behaviour. Preserve rejected outputs when assessing the model, and measure the complete review workflow.

## License and upstream components

Application source is released under the [MIT License](LICENSE). Qwen model weights and llama.cpp binaries retain their own upstream licenses. This repository contains application code and a freshly authored fictional example. The public packaging change replaces the original demo PDF and removes private reference-library paths from the writing guide; it preserves the original drafting and checking logic.
