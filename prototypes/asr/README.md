# Local ASR feasibility prototype

This isolated experiment compares Qwen3-ASR 1.7B plus its forced aligner with Parakeet TDT 0.6B v3. It does not change the app or its database. Each runner reads a source audio file, converts only the requested excerpt to temporary mono 16 kHz audio, and writes a private JSON/TXT report under `results/`.

## Machine prerequisites

- Windows 11 and an AMD GPU supported by the installed ROCm-for-PyTorch release.
- AMD's current Windows ROCm/PyTorch guide requires Python 3.12. Python 3.12.10 has been installed side by side with Python 3.15.
- For the WSL GPU path, Ubuntu 24.04 under WSL 2, AMD's ROCDXG bridge, and an isolated Python 3.12 environment with AMD's ROCm-enabled PyTorch wheels.
- `ffmpeg` on `PATH` (already available on this machine).
- Several GB of free disk space for the isolated environment and downloaded model weights. Hugging Face weights are cached outside this repository by default.

AMD's setup instructions and compatibility matrix are linked below. Do not install these ASR dependencies into the app's backend environment.

## Dependency isolation

Qwen's `qwen-asr` package pins Transformers 4.57.6, while Parakeet's current Transformers model support uses Transformers 5.x. Keep them in separate virtual environments.

For a CPU-only functional comparison, create two environments:

```powershell
py -3.12 -m venv .venv-qwen-cpu
py -3.12 -m venv .venv-parakeet-cpu

.\.venv-qwen-cpu\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.\.venv-qwen-cpu\Scripts\python.exe -m pip install qwen-asr soundfile

.\.venv-parakeet-cpu\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.\.venv-parakeet-cpu\Scripts\python.exe -m pip install "transformers>=5.0" accelerate soundfile librosa
```

For direct Windows GPU evaluation, use Python 3.12 and install AMD's ROCm PyTorch wheels using the exact commands in [AMD's Windows PyTorch install guide](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installrad/windows/install-pytorch.html), then install the model-specific packages into separate environments. The ROCm wheels installed in `.venv` for this prototype, but importing PyTorch fails on Windows with error 4551 (“An Application Control policy has blocked this file”). This prototype does not change Windows security settings. The installed AMD display driver reports Windows Driver Store version `32.0.32015.7029` (Adrenalin 26.10.1).

The WSL GPU test used AMD's [ROCDXG WSL setup](https://rocm.docs.amd.com/en/docs-7.14.0/install/rocm.html#install-rocdxg-and-amd-smi-for-wsl) and an isolated Python environment. PyTorch's HIP build reported the RX 9060 XT and completed a matrix multiplication. This confirms GPU compute works in WSL, but individual models and kernels still need testing.

Check the AMD device is visible to PyTorch before downloading model weights:

```powershell
python -c "import torch; print('torch', torch.__version__, 'HIP', torch.version.hip, 'GPU', torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU only')"
```

PyTorch uses the `torch.cuda` API surface for ROCm builds too. The report records `torch.version.hip` so the run makes clear whether ROCm or CUDA was active.

## Run an excerpt

Start with the same short excerpt for both models, then repeat on English, French, and mixed-language speech:

```powershell
.\.venv-parakeet-cpu\Scripts\python.exe run_parakeet.py "C:\path\to\recording.wav" --start 0 --duration 30 --device cpu
.\.venv-qwen-cpu\Scripts\python.exe run_qwen.py "C:\path\to\recording.wav" --start 0 --duration 30 --device cpu
```

Use `--device auto` to use a GPU when PyTorch reports one. `--start` and `--duration` select the excerpt without editing the source. The first run downloads model weights from Hugging Face; no audio is sent to a remote ASR service.

## Compare the results

Each JSON report includes provider/model, source hash and filename, excerpt offsets, detected language when available, runtime/device, model-load time, inference time, real-time factor, full transcript, and provider timestamp output. Compare:

1. Whether each model uses the GPU successfully and whether it remains stable.
2. Accuracy on the same English, French, and code-switching clips (including names, pauses, and restarts).
3. How naturally the timestamp output maps to clickable words; Parakeet reports model tokens, which may split a displayed word into multiple timed pieces.
4. Model-load time, first-run versus repeat inference time, and real-time factor.
5. Whether long recordings need chunking for memory or alignment limits.

The prototype has no ground-truth scoring because no manually verified reference transcript has been supplied. A proper word-error-rate comparison needs corrected reference text for each sample.

## Initial results on this machine

Both runners completed on CPU against two excerpts from the local development library. The excerpts were English; they are useful as a smoke test, but they are not a representative French/mixed-language journal set and have no corrected reference transcript.

| Model | Excerpt | Warm inference | Real-time factor | Timing records |
|---|---:|---:|---:|---:|
| Parakeet TDT 0.6B v3 | 10 s | 0.74 s | 0.07x | 47 model tokens |
| Parakeet TDT 0.6B v3 | 20 s | 1.25 s | 0.06x | 97 model tokens |
| Qwen3-ASR 1.7B + ForcedAligner 0.6B | 10 s | 25.44 s | 2.54x | 23 timed words |
| Qwen3-ASR 1.7B + ForcedAligner 0.6B | 20 s | 51.35 s | 2.57x | 52 timed words |

The first Parakeet model load took about 36 seconds and the first Qwen load (including its weight downloads) took about 73 seconds; those cold-start numbers are separate from inference. The direct Windows GPU setup remains blocked by Windows Application Control (WinError 4551). No Windows security setting was changed.

Parakeet is much faster on these CPU excerpts and already returns timed token pieces. Some of its tokens split a displayed word, so the app would need to merge adjacent token timings for word-click behavior. Qwen returns timed words through a separate aligner but runs slower than real time on this CPU. These timings do not establish accuracy; the excerpts were too few, English-only, and not manually verified. Do not choose a default model from these results alone.

### WSL GPU follow-up

The WSL test reused the local Hugging Face model cache and read audio from the Windows-mounted project library; the audio was not sent to a remote ASR service. The 60-second comparison uses the same first minute of a 22.5-minute recording, with word timestamps enabled for both models.

| Model | Excerpt | Device | Inference | Real-time factor | Timing records |
|---|---:|---|---:|---:|---:|
| Qwen3-ASR 1.7B + ForcedAligner 0.6B | 10 s | AMD Radeon RX 9060 XT (ROCm via WSL) | 12.97 s | 1.30x | 23 words |
| Qwen3-ASR 1.7B + ForcedAligner 0.6B | 60 s | AMD Radeon RX 9060 XT (ROCm via WSL) | 23.29 s | 0.39x | 158 words |
| OpenAI Whisper medium | 10 s | AMD Radeon RX 9060 XT (ROCm via WSL) | 24.00 s | 2.40x | 25 words |
| OpenAI Whisper medium | 60 s | AMD Radeon RX 9060 XT (ROCm via WSL) | 19.45 s | 0.32x | 157 words |
| Parakeet TDT 0.6B v3 | 10 s | AMD Radeon RX 9060 XT (ROCm via WSL) | Failed | — | — |

For the 60-second excerpt, Qwen's model load took 56.74 seconds and Whisper's cached model load took 12.08 seconds; both are separate from inference. Linear projections from the 60-second throughput would put 45 minutes of audio at roughly 17.5 minutes for Qwen and 14.6 minutes for Whisper, excluding model load. These are rough estimates from one minute, not full-recording timings, and the existing Colab Whisper run remains faster. The 10-second results are dominated by short-clip overhead and should not be extrapolated.

The two 60-second transcripts were similar in length and content, but neither was checked against a human reference. Parakeet loaded its weights, but its LSTM call failed while MIOpen compiled a kernel for `gfx1200` (`HIPRTC_ERROR_COMPILATION`). The basic PyTorch GPU check passed, so this Parakeet failure is model/kernel-specific rather than a general failure to access the GPU. Qwen inference required Ubuntu's build tools and Python headers for Triton's runtime helper.

The Qwen text has not been checked against a human reference transcript, and the excerpt was English only. This shows that Qwen can run with word timings in this WSL setup; it is not an accuracy or full-recording performance evaluation. The JSON and TXT outputs are ignored by Git under `results/`; audio and model weights remain on this computer.

## Sources

- [AMD Windows compatibility matrix](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/windows/windows_compatibility.html)
- [AMD Windows PyTorch installation](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installrad/windows/install-pytorch.html)
- [AMD ROCm 7.14 WSL installation](https://rocm.docs.amd.com/en/docs-7.14.0/install/rocm.html#install-rocdxg-and-amd-smi-for-wsl)
- [AMD Adrenalin 26.10.1 release notes](https://www.amd.com/en/resources/support-articles/release-notes/rn-rad-win-26-10-1.html)
- [OpenAI Whisper repository](https://github.com/openai/whisper)
- [Qwen3-ASR official repository](https://github.com/QwenLM/Qwen3-ASR)
- [NVIDIA Parakeet model card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)
- [Transformers Parakeet documentation](https://huggingface.co/docs/transformers/main/model_doc/parakeet)
