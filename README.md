# <p align="center">🛸 Hermes Agent — Portable & Cross-Platform with local GGUF Support</p>

<p align="center">
  <img src="https://img.shields.io/badge/Hermes_Agent-Portable-8A2BE2?style=for-the-badge&logo=ai" alt="Hermes Agent Portable">
  <img src="https://img.shields.io/github/license/NousResearch/hermes-agent?style=for-the-badge&color=2563EB" alt="License">
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-059669?style=for-the-badge" alt="Platforms">
</p>

---

<p align="center">
  <strong>Run a fully self-contained, self-improving AI agent from a single folder or USB drive.</strong><br>
  No global installation. Zero host pollution. All conversations, configs, memories, and skills stay inside your folder.
</p>

<p align="center">
  <a href="https://youtu.be/gL220WHXWeo" target="_blank">
    <img src="https://img.youtube.com/vi/gL220WHXWeo/maxresdefault.jpg" alt="Hermes Portable Setup Walkthrough Video" width="700" style="border-radius: 12px; box-shadow: 0 8px 30px rgba(0, 0, 0, 0.3); border: 1px solid rgba(255, 255, 255, 0.15);">
  </a>
  <br>
  <em>📺 <strong>Watch the Setup & Demo Video:</strong> Click the image above to watch the step-by-step walkthrough.</em>
</p>

---

## ✨ Key Features

*    **Zero Host Dependencies**: No pre-installed Python, Node.js, or package managers required on the computer. All runtimes are downloaded locally.
*    **100% Portable**: Copy the entire directory to a USB flash drive or external SSD. Run it on any Windows, macOS, or Linux computer instantly.
*    **True Privacy & Isolation**: Your API keys (`data/.env`), conversations (`data/sessions/`), persistent memory, and custom skills are kept strictly within the portable folder.
*    **Interactive Console Launcher**: Includes a beautiful terminal UI dashboard with state-tracking for setup status, LLM providers, and background gateways.
*    **Full Hermes Capabilities**: Retains all features of [Nous Research's Hermes Agent](https://github.com/NousResearch/hermes-agent), including memory storage and reusable skill generation.
*    **Local `.gguf` Model Support**: Load local GGUF models through Hermes' managed llama.cpp runtime (`--local-model <path>`). Installs llama.cpp automatically when missing, stages the model, starts the local server, and shuts it down when the CLI exits — fully offline, no cloud API keys required.

---

## ⚡ Quick Start

Get Hermes running in seconds depending on your operating system:

### Windows (10 / 11)
Simply double-click the **`launch.bat`** file in this folder.
> *Note: On first run, it will launch a PowerShell window to download dependencies and configure your runtime environment.*

###  macOS & Linux
Open your terminal in this directory and execute:
```bash
chmod +x launch.sh
./launch.sh
```

> 💡 **macOS Double-Click Shortcut:** If you want to double-click in Finder to launch, rename `launch.sh` to `launch.command`. macOS recognizes `.command` files and opens them in Terminal automatically.

---

## ⚙️ How It Works (Under the Hood)

Hermes Portable solves the host-dependency issue by establishing a sandboxed runtime context pointing inwards.

```mermaid
graph TD
    A[User triggers launch script] --> B{Runtimes setup?}
    B -- No / First Run --> C[Download Portable Python 3.14 & Node.js 22]
    C --> D[Clone Hermes Agent Source to src/]
    D --> E[Create isolated virtual env using uv]
    E --> F[Install Python & Node packages locally]
    F --> G[Generate ready.flag]
    B -- Yes / Ready --> H[Configure environment variables]
    G --> H
    H --> I[Set HERMES_HOME = data/]
    I --> J[Prepend portable bin/ paths to Env PATH]
    J --> K[Auto-start Gateway in background]
    K --> L[Launch Terminal Dashboard Menu]
    L --> M[Start Gateway + Chat → Stop Gateway]
    L --> N[Load local .gguf via --local-model]
    N --> O[Ensure llama.cpp engine installed]
    O --> P[Sideload .gguf into models dir]
    P --> Q[Start supervised llama-server]
    Q --> R[Route CLI at local model]
    R --> S[Chat locally — no cloud API key]
```

### The Isolation Design
1. **Custom Data Directory**: The launcher overrides `HERMES_HOME` to the local `data/` folder, forcing Hermes to write configuration and data locally rather than in `~/.hermes/`.
2. **Local Path Sandboxing**: The scripts download self-contained Python and Node.js binaries into `.cache/runtimes/` and prepend them directly to the active process `PATH`.
3. **No Registry/Host Pollution**: System configurations, environment variables, or packages on the host machine are left untouched.
4. **Self-Contained Gateway Lifecycle**: The gateway starts automatically in the background when the launcher opens, so messaging is live while the menu is shown. **Start Gateway + Chat** opens the CLI in its own console and stops the gateway when the CLI exits if this action started it. Process control uses only the bundled Python (`scripts/gateway_control.py`) — no Windows services, Scheduled Tasks, PowerShell, or host tools.

---

## 📁 Workspace Directory Structure

A clean, modular layout where runtime caches are separated from your personal configurations.

```yaml
hermes-portable/
├── launch.bat                 # Windows interactive launcher script
├── launch.sh                  # macOS & Linux interactive launcher script
├── scripts/
│   ├── gateway_control.py     # Portable gateway start/stop/status/chat helper
│   ├── setup-windows.ps1      # Windows first-run configuration script
│   └── setup-unix.sh          # Unix (macOS/Linux) first-run configuration script
├── data/                      # ⚠️ [BACKUP THIS] All your private files
│   ├── config.yaml            # Hermes LLM provider configurations
│   ├── .env                   # API Keys and active credentials
│   ├── sessions/              # Chronological chat histories
│   ├── memories/              # Persistent memory databases
│   └── skills/                # Learned custom skills
├── src/                       # Downloaded Hermes Agent source code
│   └── hermes-agent/
└── .cache/                    # Sandbox cache & binaries
    └── runtimes/              # Platform-specific portable interpreters
        ├── windows-x64/
        ├── macos-arm64/
        ├── macos-x64/
        ├── linux-x64/
        └── linux-arm64/
```

---

## 🗝️ Setup API Keys

To configure your language models, open and edit the environment variables in `data/.env`:

```env
# Add the keys for the providers you wish to use:
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxx
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxx
```

Alternatively, you can select option **`[2]` (Setup / Reconfigure)** in the Launcher Terminal Menu to configure model providers interactively.

---

## 🧠 Using a Local Ollama Instance

Hermes Portable can use an Ollama server that is already running on the same computer. Start Ollama first, then pull a model:

```bash
ollama pull qwen3.6
```

Launch Hermes Portable and choose **`[2]` Setup / Reconfigure Hermes**. In the Hermes setup wizard:

1. Choose **Quick setup**.
2. Select **More providers**.
3. Select **Custom endpoint (enter URL manually)**.
4. Enter the local OpenAI-compatible Ollama endpoint:

```text
http://127.0.0.1:11434/v1
```

5. Leave the API key blank when prompted.
6. Select the detected Ollama model and leave context length blank to auto-detect it.

For a remote Ollama host, use the same `/v1` endpoint format, for example `http://192.168.1.20:11434/v1`. Make sure the Ollama host is reachable from the computer running Hermes Portable.

---

## 🦙 Using local Llama.cpp server and loading local .GGUF models

Hermes Portable can run models entirely offline using local `.gguf` files through its **managed llama.cpp server**. When you pass `--local-model <path>`, Hermes:

1. Validates the `.gguf` file exists
2. **Installs llama.cpp automatically** (via PM) when no engine is present
3. Sideloads the model into the managed `data/models/` directory
4. Starts the supervised `llama-server` on a local loopback port
5. Routes the current chat at that local model — no cloud API key needed
6. **Stops the server when the CLI exits** (portable, leaves nothing running)

### Usage

```bash
# Windows (launch.bat)
launch.bat --local-model "C:\path\to\model.gguf"
launch.bat chat --local-model "models/meta-llama-3.1-8b-instruct.Q4_K_M.gguf"

# macOS / Linux (launch.sh)
./launch.sh --local-model "/path/to/model.gguf"
./launch.sh chat --local-model "/path/to/model.gguf"
```

Or with the `hermes` CLI directly:

```bash
hermes --local-model /path/to/model.gguf -q "Hello, who are you?"
hermes chat --local-model /path/to/model.gguf
```

### Recommended local .GGUF models

The table below lists efficient, capable GGUF models suitable for portable/local execution. Pick a quantisation that fits your available RAM/VRAM — lower-bit Q4_K_M or Q5_K_M runs well on CPU-only machines, while Q6_K / Q8_0 needs more memory but better quality.

| Model | Type | Size (Q4) | CPU-only RAM | Recommended VRAM | Best For | Capabilities |
|-------|------|-----------|--------------|------------------|----------|--------------|
| **Llama-3.1-8B-Instruct** | General / Efficient | ~4.7 GB | 8 GB | 6 GB | General chat, coding, reasoning | Strong generalist, tool use, multilingual |
| **Qwen2.5-Coder-7B-Instruct** | Coder | ~4.3 GB | 8 GB | 6 GB | Code generation, debugging | Excellent coding, math, reasoning |
| **CodeLlama-7B-Instruct** | Coder | ~4.1 GB | 8 GB | 6 GB | Code completion, infill | Python/SQL/Java focus, fill-in-the-middle |
| **Phi-3.5-mini-instruct** | Efficient / Small | ~2.2 GB | 4 GB | 3 GB | Low-spec machines, fast replies | Good general chat, small footprint |
| **Gemma-2-9B-IT** | General | ~5.4 GB | 10 GB | 8 GB | Instruction following, reasoning | Strong alignment, safe responses |
| **Nemotron-H / Nemotron-Mini** | Efficient / Coder | ~4.0–8.0 GB | 8–16 GB | 6–10 GB | Coding, agentic workflows | Tool use, function calling, reasoning |
| **Abiterated / Uncensored variants** | Uncensored | ~4–9 GB | 8–16 GB | 6–10 GB | Open-ended generation, roleplay | Fewer refusals, creative writing |
| **NSFW / DAN-compatible variants** | Uncensored | ~4–9 GB | 8–16 GB | 6–10 GB | Adult content, jailbreak-style prompts | Minimal safety filters, unfiltered |

> ⚠️ **Content warning**: Uncensored / abilterated / NSFW / DAN-compatible GGUFs have reduced or no safety filtering. Use them responsibly and only in private, isolated environments. You are solely responsible for the content you generate.

### Quantisation guide

| Quant | Quality | VRAM/RAM | Speed | Use case |
|-------|---------|----------|-------|----------|
| **Q2_K / Q3_K_S** | Low | Smallest | Fastest | Very low RAM devices |
| **Q4_K_M** | Good | Balanced | Fast | **Recommended default** for most |
| **Q5_K_M** | Better | Medium | Medium | Better reasoning, still efficient |
| **Q6_K** | Very good | Large | Slower | High-quality on capable hardware |
| **Q8_0** | Near-fp16 | Largest | Slowest | Maximum quality, high-end GPUs |

### Notes

* The first run downloads and installs llama.cpp (~200–400 MB depending on platform).
* GGUF models are stored under `data/models/` and shared across all profiles.
* The local server binds to `127.0.0.1` only — it is never exposed to the internet.
* When the Hermes CLI exits, the managed llama-server shuts down automatically (portable behavior).

---

## 🖥️ Supported Platforms

| Operating System | CPU Architecture | Setup Status | Notes |
| :--- | :--- | :--- | :--- |
| **Windows 10 / 11** | x86_64 | ✅ Supported | Default Powershell ExecutionPolicy bypassed for script |
| **macOS 13+** | Apple Silicon (ARM64) | ✅ Supported | Native M1/M2/M3 execution |
| **macOS 13+** | Intel (x86_64) | ✅ Supported | Legacy Intel Mac support |
| **Linux (Ubuntu/Arch/Debian)** | x86_64 | ✅ Supported | Fully self-contained |
| **Linux (Fedora/CentOS)** | ARM64 | ✅ Supported | Supports SBCs and ARM Servers |

---

## 📦 Cache & Runtime Footprint

The current Windows x64 full first-run setup was measured at about **1.5 GB total** after setup completed.

| Component | Measured / Expected Size | Notes |
| :--- | :--- | :--- |
| **Launchers & Scripts** | <1 MB | Metadata and setup automation scripts |
| **Windows x64 Runtime** | ~800 MB | Python, Node.js, uv, Git, ripgrep, venv, and downloaded archives |
| **Playwright / Local App Cache** | ~400 – 500 MB | Chromium browser cache used by Hermes web tools |
| **Hermes Source Code** | ~100 MB | Downloaded Hermes Agent source tree |
| **User Data** | ~10 MB → 2 GB+ | Grows as memory, logs, sessions, skills, and backups accumulate |

Recommended USB / external drive free space:

| Use Case | Free Space to Reserve |
| :--- | :--- |
| **One platform only** | **2 GB minimum**, **4 GB recommended** |
| **Windows + one Unix platform** | **4 – 6 GB recommended** |
| **Windows + macOS + Linux runtimes** | **8 GB+ recommended** |
| **Heavy long-term use with many sessions/backups** | **16 – 32 GB recommended** |

> ℹ️ *Each operating system and CPU architecture gets its own `.cache/runtimes/<platform>-<arch>/` folder, so using the same USB drive across Windows, macOS, and Linux will increase storage usage.*

---

## 🔄 Updating Hermes Agent

Keep your agent up-to-date with the latest improvements from Nous Research:

*   **Via Chat Command**: Within an active Hermes conversation, type:
    ```text
    /hermes update
    ```
*   **Via Launcher**: Navigate to `[4] Advanced Options` -> `[5] Update Hermes` in the Launcher terminal dashboard.
*   **Manual Rebuild**: Delete `.cache/runtimes/<your-platform>` and the `src/hermes-agent` directory, then re-run the launcher to fetch the latest code from scratch.

---

## 🔒 Security Advisory

> [!WARNING]
> **Your portable directory contains your identity.**
> Because `data/.env` stores raw API keys and `data/sessions/` contains logs of your conversations, anyone with access to your portable drive can access your accounts.
> 
> *   **Recommended Action**: Encrypt your USB flash drive or SSD using **BitLocker** (Windows), **FileVault** (macOS), or a cross-platform utility like **VeraCrypt**.
> *   Avoid storing large API balances or production keys on drives you carry daily.

---

## 🔍 Troubleshooting & FAQ

<details>
<summary><strong> First-run setup fails or times out</strong></summary>

*   Verify your internet connection (the setup downloads ~600 MB of data).
*   Some corporate/school firewall settings block Node.js CDNs or GitHub releases. Try configuring a VPN.
*   Delete the `.cache/` folder and launch again to clean-install the runtimes.
</details>

<details>
<summary><strong> macOS: "cannot be opened because the developer cannot be verified"</strong></summary>

*   Right-click `launch.sh` (or `launch.command`), choose **Open With** and select **Terminal**.
*   Alternatively, open terminal and strip macOS quarantine flags using:
    ```bash
    xattr -dr com.apple.quarantine /path/to/hermes-portable
    ```
</details>

<details>
<summary><strong> Windows Defender flags the launcher scripts</strong></summary>

*   This is a false positive caused by PowerShell scripts downloading files from remote sources (GitHub & Node.js servers).
*   Click **"More info"** on the Windows SmartScreen dialog, then click **"Run anyway"**.
*   The setup scripts are fully open-source and human-readable under the `scripts/` directory for your inspection.
</details>

<details>
<summary><strong> Hermes is running slowly from my flash drive</strong></summary>

*   Older USB 2.0 drives have slow read/write speeds, which bottleneck Python's modules import.
*   **Solution**: Upgrade to a **USB 3.0 / 3.1** drive, or an **external SSD** for optimal performance.
</details>

<details>
<summary><strong> Playwright / Web Browser tools are failing</strong></summary>

*   Some OS sandboxing policies restrict web browsers (Chromium/Firefox) from starting directly inside external/removable directories.
*   **Solution**: Copy the `hermes-portable` directory onto the local SSD and run from there.
</details>

---

## 📝 Credits & Attribution

*   **[Hermes Agent](https://github.com/NousResearch/hermes-agent)** — Powerful Agentic core created by [Nous Research](https://github.com/NousResearch).
*   **[python-build-standalone](https://github.com/indygreg/python-build-standalone)** — Portable Python interpreter compilation.
*   **[uv](https://github.com/astral-sh/uv)** — Blazing fast package installer and resolver.
