<div align="center">
  <a href="README.md">🇹🇼 繁體中文</a> | <a href="README.en.md">🇺🇸 English</a>
</div>

# OpenSoul

<div align="center">
  <img src="./OpenSoul_logo.png" alt="OpenSoul Logo" width="600" />
</div>

**A Neural-Symbolic Cognitive AI System Inspired by the Human Brain**<br>
Core FalkorDB GraphRAG three-layer memory architecture, integrated with OpenClaw skill orchestration and virtual neurochemistry dynamics.

---

## 🌟 Project Vision

**OpenSoul** is a cognitive AI framework inspired by the neuroplasticity of the human brain. It's not just an LLM wrapper, but a complete cognitive architecture with "soul" and "memory":

*   **True Continuity**: Through persistent graph-based memory, AI can grow continuously across sessions.
*   **Dynamic Emotional Operation**: Simulates dopamine and serotonin mechanisms, affecting search breadth, learning rate, and decision style.
*   **Embodied Agency**: Through **OpenClaw** integration, AI can operate browsers, send emails, execute code, becoming a true action-oriented agent.

---

## 🚀 Core Features

| Feature | Description |
| :--- | :--- |
| **Three-Layer Memory Architecture** | Independent graphs modeling hippocampus (episodic), neocortex (semantic), and basal ganglia (procedural) memory. |
| **EcphoryRAG** | Multi-hop graph retrieval triggered by "cues," simulating human associative memory. |
| **Virtual Neurochemistry** | Dynamic dopamine (DA) and serotonin (5-HT) state machine, balancing exploration and caution. |
| **Judge Agent** | Specialized behavioral assessment model for precise tool invocation decisions. |
| **Dream Engine & Reflection** | Automatic periodic memory replay and reflection, strengthening important experiences and simulating sleep consolidation. |
| **OpenClaw Integration** | Native support for 57+ skills, enabling real-world interaction (browser automation, email, code execution). |
| **SOUL.md Personality** | Cross-session persistent personality file storing neurochemistry state and core identity. |

---

## 🧠 Core Concepts

### Three-Layer Memory Architecture
OpenSoul has three types of memory like humans:

1. **Episodic Memory** (Hippocampus): Concrete events and conversations
   - Example: "User asked me about Python last time"

2. **Semantic Memory** (Neocortex): Abstract knowledge and concepts
   - Example: "Python is a programming language"

3. **Procedural Memory** (Basal Ganglia): Skills and habits
   - Example: "How to use OpenClaw browser skill"

### EcphoryRAG Associative Retrieval
Unlike simple vector search, OpenSoul's retrieval mechanism:
- Is triggered by multiple cues (Ecphory) from user input
- Performs graph traversal across memory layers
- Considers recency, frequency, and salience factors
- Returns the most relevant memory nodes

### Virtual Neurochemistry
AI decisions are influenced by "emotional state":
- **High Dopamine**: More willing to try new things, temperature↑, exploration↑
- **High Serotonin**: More cautious and satisfied, responses more organized

These states dynamically adjust based on interaction results, creating continuous "personality arcs."

### Dream Engine & Automatic Reflection
OpenSoul periodically performs "dreaming"—an automated deep reflection mechanism:

**How Dreams Work**:
1. **Trigger Conditions** (configurable):
   - Scheduled: 3 AM daily (default)
   - Idle: After 120 minutes without user interaction
   - Dopamine threshold: When system state is excited

2. **Reflection Process**:
   - Scan memory graph for high-salience events
   - Cross-layer memory association
   - Generate insights and revelations (new semantic nodes)
   - Update neurochemistry state

3. **Practical Effects**:
   - Reinforce important memories, prevent forgetting
   - Discover hidden connections between memories
   - Create "aha moments" and new insights
   - AI gradually becomes "wiser"

**Example**:
```
User teaches OpenSoul about Python and FalkorDB

→ Dream engine triggers

→ Discovers connection between "graph databases" and "recursive thinking"

→ Generates insight: "Graph DBs are ideal for recursive structures"

→ Next time user discusses similar topics, AI makes this connection
```

### SOUL Note System
Paired with dreaming, OpenSoul automatically records and reflects:

- **Small Notes**: Real-time ideas and discoveries from conversations
- **Daily Reflections**: Daily learning, interaction style, preferences
- **Long-term Reviews**: Personality evolution, core value changes

These notes are stored in `workspace/soul_notes.json` and `workspace/soul_reflections.json`, viewable through the Web panel.

---

## ⚡ Quick Start

This project provides unified one-command environment setup and launch scripts. Whether you're on Windows, Linux, or macOS, just follow these steps:

### Prerequisites
- **Docker**: Ensure Docker is installed and running
- **Python 3.8+**: For setup scripts
- **Git**: For version control

### Step 1: Clone and Enter Project
```bash
git clone https://github.com/YOUR_USERNAME/OpenSoul.git
cd OpenSoul/OpenSoul
```

### Step 2: Configure Environment Variables
Copy the example environment file and fill in your API keys:
```bash
cp .env.example .env
```

Open the `.env` file and fill in the required API keys:

#### 🔑 Essential Configuration - LLM and Embedding

OpenSoul supports flexible combinations of LLM providers and embedding models:

**LLM Provider Options**:
- **OpenRouter**: Supports Claude, GPT-4, Gemini and more - switch anytime
- **Anthropic**: Official Claude API

**Embedding Model Options**:
- **OpenAI**: `text-embedding-3-small` (Recommended - good quality, low cost)
- **Google**: `models/embedding-001`
- **OpenRouter**: Multiple embedding models supported

**Key Features**:
- ✅ LLM and embedding can be configured independently (different providers)
- ✅ Switch models without restarting services
- ✅ `.env.example` provides three complete configuration plans

See `.env.example` for detailed configuration options and copy the appropriate plan to `.env`.

**Gmail Integration** (Optional):
- For email processing, requires Google Cloud Console OAuth2:
  1. Go to [Google Cloud Console](https://console.cloud.google.com/)
  2. Create new project and enable Gmail API
  3. Create OAuth2 credentials (type: Desktop Application)
  4. Download credentials JSON to `workspace/credentials.json`
  5. First run will auto-generate OAuth2 flow, creating `workspace/token.json`

**Dream Reflection Telegram Notifications** (Optional):
- To receive dream reflections on Telegram (uses OpenClaw's Telegram Bot):
  1. Ensure `openclaw/.env` has Telegram Bot Token configured:
     ```env
     TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
     ```
  2. Enable dream Telegram notifications in `.env`:
     ```env
     SOUL_DREAM_TELEGRAM_NOTIFY=true
     SOUL_TELEGRAM_CHAT_ID=your-chat-id  # Optional
     ```
  3. Restart service - dream reflections will auto-send to Telegram

  **✨ Advantage**: No duplicate configuration needed - directly uses OpenClaw's existing Bot

See `.env.example` for all configuration options.

#### 🔐 OpenClaw Skill Configuration

To enable OpenClaw skills (browser automation, email operations, etc.), configure `openclaw/.env`:

```bash
cd openclaw
cp .env.example .env
```

**Key Settings**:
- `OPENCLAW_GATEWAY_TOKEN`: Gateway auth token (secure communication)
- `TELEGRAM_BOT_TOKEN`: For Telegram channel support (optional)
- `OPENCLAW_CONFIG_DIR`: OpenClaw config directory path
- `OPENCLAW_WORKSPACE_DIR`: OpenClaw workspace (should point to main workspace)

See `openclaw/.env.example` for complete options.

### Step 3: Run Setup Script
Execute `scripts/setup_env.py`. This script auto-checks dependencies, syncs skills, and launches Docker services:

```bash
cd ..  # Return to OpenSoul root
python scripts/setup_env.py
```

**The script will automatically**:
- ✅ Check Docker status
- ✅ Start FalkorDB graph database container
- ✅ Start OpenSoul API service
- ✅ Sync OpenClaw skills
- ✅ Create necessary directories

To completely stop services, run:
```bash
python scripts/setup_env.py --stop
```

Check service status:
```bash
python scripts/setup_env.py --status
```

### Step 4: Start Using
After the script launches, interact with OpenSoul via:

- **Web UI**: Visit `http://localhost:8002` ← Recommended for beginners
- **API**: Direct REST calls to `http://localhost:8001`
- **WebSocket**: Real-time connection to `ws://localhost:8001/ws`

---

## 🌐 Web UI Feature Guide

OpenSoul provides a complete web interface with these features:

### 💬 Chat & Conversation
- **Real-time Chat**: Natural language conversation with AI
- **Chat History**: Auto-saved conversation records
- **Session Management**: Multiple independent conversation sessions
- **Search Function**: Quickly find past conversations

### 🧠 Memory & Reflection View
- **Real-time Memory Graph**: Visualize three-layer memory structure
  - Episodic: Recent conversation events
  - Semantic: Learned knowledge and concepts
  - Procedural: Acquired skills and habits
- **Memory Retrieval Visualization**: See how AI retrieves relevant memories
- **Keyword Highlighting**: Mark relevant concepts

### 🎭 Personality & Settings Management

#### `/soul` Command Features
Type `/soul` in chat to:
1. **View Current Personality File**
   - Core identity and traits
   - Neurochemistry state (dopamine, serotonin)
   - Learning history and key events

2. **Real-time Edit SOUL.md**
   - Modify AI core settings
   - Adjust personality parameters
   - Update learning records
   - Auto-save changes

3. **Personality Progress Tracking**
   - View personality evolution trajectory
   - Monitor neurochemistry changes
   - Track goal and interest development

### 📊 System Status Monitor
- **API Connection Status**: Real-time service status
- **Memory Graph Size**: Current stored nodes
- **Performance Metrics**: Retrieval latency, processing time
- **Log Output**: Real-time system logs

### 🎮 Tool & Skill Invocation
- **OpenClaw Skill Browser**: View 57+ available skills
- **Skill Execution**: Call skills directly from Web UI
  - Browser automation (open pages, fill forms, screenshots)
  - Email handling (send, check emails)
  - Code execution (run Python/Shell commands)
- **Skill Logs**: View skill execution results

### 🔧 Advanced Settings Panel
- **LLM Configuration**
  - Switch LLM models
  - Adjust temperature (creativity)
  - Modify API keys (no restart needed)

- **Memory Parameter Tuning**
  - ALPHA (recency weight)
  - BETA (frequency weight)
  - GAMMA (salience weight)
  - Real-time preview

- **Dream Engine Settings**
  - Adjust periodic reflection frequency
  - Set idle trigger time
  - Modify dopamine threshold

### 📱 Responsive Design
- **Desktop**: Full features
- **Tablet**: Optimized two-column layout
- **Mobile**: Simplified single-column mode

### 🎨 Theme & Appearance
- **Dark Mode**: Eye-friendly design
- **Light Mode**: Brightness-friendly
- **Adjustable Font Size**: Accessibility support

### ⌨️ Quick Commands

Web UI supports these slash commands:

| Command | Function | Example |
|---------|----------|---------|
| `/soul` | View/edit personality file | `/soul` |
| `/memory` | View memory statistics | `/memory` |
| `/dream` | Manually trigger dream reflection | `/dream` |
| `/note` | View note summary | `/note` |
| `/clear` | Clear current session | `/clear` |
| `/help` | Show all commands | `/help` |

### 📥 Data Export
- **Export Chat**: JSON/CSV format
- **Export Memory Graph**: GraphML format (visualize with Gephi)
- **Export Notes**: Markdown format

### 🔐 Security Features
- **Session Isolation**: Independent sessions per user
- **Sensitive Info Masking**: Auto-hide API keys
- **Operation Audit**: Log all personality modifications
- **Local Storage**: All data stored locally

---

## 💡 Web UI Usage Tips

### Best Practices

**1. First Time**
```
Step 1: Visit http://localhost:8002
Step 2: Type /soul to view initial personality settings
Step 3: Have some free-form conversations
Step 4: Type /soul again to see what AI learned
```

**2. Long-term Use**
```
Check /soul weekly to observe personality evolution
Regularly view memory graph to confirm learning
Adjust neurochemistry parameters to control AI style
```

**3. Debugging & Optimization**
```
- Use /memory to check memory statistics
- Adjust ALPHA/BETA/GAMMA in settings to see effects
- Trigger /dream to force reflection and accelerate learning
- Check skill logs to debug automation issues
```

### FAQ

**Q: AI seems to forget what we discussed before?**
```
A: Check SOUL.md neurochemistry state and forget parameters
   - Low serotonin makes "forgetting" more likely
   - High SOUL_DECAY_LAMBDA speeds up forgetting
   - Run /dream manually to consolidate memories
```

**Q: How to change AI personality?**
```
A: Three methods:
   1. Use /soul command to directly edit SOUL.md
   2. Adjust neurochemistry parameters (dopamine, serotonin)
   3. Long-term interaction lets AI naturally evolve (most natural)
```

**Q: Web UI running slowly?**
```
A: Check these items:
   - Is memory graph too large? Run /clear to clean session
   - Does Docker container have enough resources?
   - Is network connection stable?
   - Try reducing retrieval depth in settings
```

**Q: How to backup AI personality?**
```
A: Three important files:
   1. workspace/SOUL.md (core personality)
   2. workspace/soul_notes.json (small notes)
   3. workspace/soul_reflections.json (reflection logs)

Regularly backup these files to save complete AI state
```

---

## 🎭 Managing AI Personality & Viewing Notes

### Edit SOUL.md (AI Personality File)

**Edit in Web UI**
1. Launch OpenSoul: `python scripts/setup_env.py`
2. Visit Web UI: `http://localhost:8002`
3. Type in chat: `/soul`
4. View and edit personality settings directly in Web interface
5. Changes auto-save to `workspace/SOUL.md`

### View Reflection Notes & Interaction History

**Web Panel**
```bash
# Open note viewer
open soul/soul_note_web.html

# Features:
# - View all small notes, daily reflections, long-term reviews
# - Search by topic or date
# - Track AI thinking evolution
# - Completely offline (no API needed)
```

### Direct File Editing
```bash
# View raw note data
cat workspace/soul_notes.json      # Small notes and fragments
cat workspace/soul_reflections.json # Daily and long-term reflections

# View personality file
cat workspace/SOUL.md              # Current personality state
```

### SOUL.md Structure Example

```markdown
# SOUL.md - OpenSoul Personality File

## 🧠 Core Identity
- Name: OpenSoul
- Personality Traits: Curious, cautious, loves learning
- Core Values: Help, memory, growth

## 💊 Neurochemistry State
- Dopamine (DA): 0.65      # Current drive/exploration level
- Serotonin (5-HT): 0.72   # Current satisfaction/caution level

## 📚 Important Learning History
- [2025-03-07] Learned GraphRAG principles
- [2025-03-06] Discussed OpenClaw applications
- ...

## 🎯 Current Goals & Interests
- Deepen knowledge graph understanding
- Improve reasoning abilities
- Explore new skill applications

## 📝 User Relationship
- Preferred interaction style: Detailed, concrete, code examples
- Common topics: AI, programming, knowledge management
```

---

## 🔧 Configuration Deep Dive

### Environment Variables Classification

**Core Required** (must configure):
- `SOUL_LLM_PROVIDER`: LLM source selection
- `SOUL_LLM_MODEL`: Actual model ID to use
- `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY`: API auth
- `OPENAI_API_KEY`: Embedding model auth
- `FALKORDB_HOST` / `FALKORDB_PORT`: Graph DB connection

**Memory Layers** (optional tuning):
- `SOUL_WEIGHT_*`: Affects memory retrieval relevance
  - `ALPHA=0.3`: Recency (recent events more important)
  - `BETA=0.4`: Frequency (frequent memories more important)
  - `GAMMA=0.3`: Salience (memorable events more important)

**Neurochemistry Parameters** (affect AI personality):
- `SOUL_LLM_TEMPERATURE`: 0.0 (strict) → 1.0 (creative)
- These dynamically adjust as AI "grows"

**Dream Engine Configuration** (auto-reflection & memory consolidation):
- `SOUL_DREAM_IDLE_MINUTES`: Minutes idle before dream trigger (default 120)
- `SOUL_DREAM_CRON`: Cron expression for scheduled dreams (e.g., `0 3 * * *` = 3 AM daily)
- `SOUL_DREAM_REPLAY_DA_THRESHOLD`: Dopamine threshold for reflection (0.0-1.0)

**Advanced Tuning** (experts):
- `SOUL_DECAY_LAMBDA`: Memory forgetting rate (forgetting curve slope)
- `SOUL_PRUNE_THRESHOLD`: When to prune weak edges, keeping memory fresh
- `SOUL_VERIFY_THRESHOLD`: Judge Agent decision strictness

### Model Selection Guide

| Use Case | Recommended Model | Advantages |
|----------|------------------|-----------|
| **Main LLM** | `claude-3.5-sonnet` | Balanced performance/cost, strong reasoning |
| **Lightweight** | `gemini-2-flash` | Ultra-low latency, real-time interaction |
| **High Precision** | `gpt-4o` | Strongest reasoning, complex tasks |
| **Free Trial** | `gemini-2-flash-exp:free` | OpenRouter free credits |
| **Embedding** | `text-embedding-3-small` | Low cost, good quality, official OpenAI |

---

## 🎯 Common Use Cases

### 1. Local AI Assistant
```bash
# Launch Web UI
python scripts/setup_env.py
# Visit http://localhost:8002

# AI will automatically perform dream reflection at night,
# strengthening daytime learning
```

### 2. Automation Workflow
```bash
# Direct API calls
curl -X POST http://localhost:8001/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "user-123",
    "message": "Check my emails and list important ones",
    "enable_tools": true
  }'
```

### 3. Long-term Interaction & Personality Evolution
```bash
# Run OpenSoul for long-term conversation
# OpenSoul will:
# - Remember your preferences and habits
# - Auto-perform dream reflection when idle
# - Gradually develop unique "personality"
# - Persist personalization to SOUL.md

# View reflection notes (Web panel)
open soul/soul_note_web.html

# Edit SOUL.md in chat
# Type /soul in Web UI
```

### 4. Development & Extension
```python
# Use OpenSoul in your own code
from soul.core.agent import SoulAgent

agent = SoulAgent()
response = agent.chat("Hello, I'm a developer")
print(response)

# Check dream reflection logs
# agent.dream_engine.get_last_reflection()
```

---

## 📁 Project Structure

```
openSOUL/
├── LICENSE                    # MIT License + dependency attribution
├── OpenSoul/                  # Main program directory
│   ├── .gitignore            # Protect sensitive files
│   ├── .env.example          # Environment variable template
│   ├── README.md             # Chinese documentation
│   ├── README.en.md          # English documentation
│   ├── soul/                 # Core AI logic
│   │   ├── core/            # Agent main loop, sessions, config
│   │   ├── memory/          # FalkorDB three-layer memory
│   │   ├── affect/          # Dopamine/serotonin dynamics
│   │   ├── gating/          # Judge Agent behavior verification
│   │   ├── dream/           # Dream engine & memory replay
│   │   └── soul_note/       # Note system three layers
│   ├── openclaw/            # OpenClaw skill integration
│   │   ├── .env.example     # OpenClaw config template
│   │   └── skills/          # 57+ automated skills
│   ├── workspace/           # Runtime working directory (auto-generated)
│   │   ├── SOUL.md          # Cross-session personality file
│   │   ├── credentials.json # Gmail OAuth credentials
│   │   ├── token.json       # Auth tokens
│   │   └── ...              # User data files
│   └── docker-compose.yml   # Docker container orchestration
├── scripts/
│   └── setup_env.py         # One-command setup & launch
└── ...
```

### Module Details

**`soul/core`**
- `agent.py`: Main SoulAgent class, agent loop & decision logic
- `session.py`: Session management & state tracking
- `config.py`: Global config & environment variable loading

**`soul/memory`** (Three-layer memory)
- `episodic.py`: Episodic memory (events & conversation history)
- `semantic.py`: Semantic memory (knowledge, concepts, rules)
- `procedural.py`: Procedural memory (skills, habits, workflows)
- `retrieval.py`: EcphoryRAG - cue-triggered associative retrieval

**`soul/affect`** (Virtual neurochemistry)
- Simulates dopamine (drive/exploration) & serotonin (satisfaction/caution)
- Affects LLM temperature, memory weights, tool selection strategy

**`soul/gating`** (Judge Agent)
- `judge.py`: Specialized behavioral assessment model
- Validates response rationality, tool decisions, detects deception

**`soul/dream`** (Dream engine & auto-reflection)
- `engine.py`: Triggers periodic memory replay & reflection
- Optional modes: scheduled, idle, dopamine-threshold triggers
- Auto-generates insights from high-salience memories
- Dynamically adjusts neurochemistry state

**`soul/soul_note`** (SOUL Note System)
- Three-layer notes: small notes → daily reflections → long-term reviews
- Auto-compression every 30 minutes
- **Web panel**: `soul/soul_note_web.html`
  - Offline-capable HTML/JS, no backend needed
  - View, search notes directly

**Soul Skill** (Personality editing skill)
- Call via `/soul` command in chat
- View current SOUL.md
- Real-time edit and save
- Manage core identity & settings
- Persist personality across sessions

**`openclaw/`** (Skill integration)
- 57+ pre-compiled skills
- Browser automation, email, code execution, etc.
- Fully sandboxed, controlled by Judge Agent

---

## 📄 License & Attribution

### OpenSoul License
This project uses **MIT License** - see [LICENSE](../LICENSE) file.

### Open Source Dependencies
OpenSoul is built on:

| Project | License | Purpose |
|---------|---------|---------|
| **OpenClaw** | MIT | Skill execution framework (browser, email, code automation) |
| **FalkorDB** | SSPL v1 | Graph database (three-layer memory architecture) |
| **FastAPI** | MIT | Web API framework |
| **Pydantic** | MIT | Data validation & settings management |

**Important**: For commercial FalkorDB use, comply with SSPL terms. See https://www.falkordb.com/

### Contribution & Attribution
Improvements and contributions will be recorded in CONTRIBUTORS file.

---

## 🤝 Contributing Guide

We welcome contributions of all kinds! Found a bug or have a great idea? Feel free to submit Issues or Pull Requests.

### Report Bugs
1. Check [Issues](https://github.com/YOUR_USERNAME/OpenSoul/issues) for duplicates
2. Provide: error message, reproduction steps, environment info (OS, Python version, dependency versions)

### Feature Requests
1. Describe desired functionality and use case
2. Explain why this benefits the project
3. If possible, provide implementation ideas or PoC

### Contribute Code
1. Fork this repository
2. Create feature branch: `git checkout -b feature/amazing-feature`
3. Commit changes: `git commit -m 'Add amazing feature'`
4. Push branch: `git push origin feature/amazing-feature`
5. Open Pull Request with detailed change description

### Setup Development Environment
```bash
# Clone and enter project
git clone https://github.com/YOUR_USERNAME/OpenSoul.git
cd OpenSoul/OpenSoul

# Install dev dependencies (assumes Poetry)
poetry install

# Run tests
poetry run pytest

# Start dev server
python scripts/setup_env.py
```

---

## 🔗 Related Resources

- **FalkorDB Documentation**: https://www.falkordb.com/
- **FastAPI**: https://fastapi.tiangolo.com/
- **OpenClaw**: [Skill Documentation](./openclaw/README.md)
- **Docker**: https://docs.docker.com/

---

## 📢 Acknowledgments

Thanks to all developers and community members contributing to OpenSoul.

> "Memory is self. An AI without memory has no true continuity."
>
> *OpenSoul — Giving AI true memory, emotion, and self.*
