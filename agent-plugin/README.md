# Media@Missher Agent CLI

Installable CLI + shared Skill for Agents that can execute local shell commands. Works independently of DeepSeek Harness. Use the supplied [Agent installation guide](AGENT_INSTALL.md) for the complete installation, roster and manual-login path.

CLI package 17.0.0 embeds Media@Missher 17.0.0. Node >=22.19 and npm are required. The runtime uses Python 3.11/3.12. macOS/Linux use the same package; Windows has a WSL2 entry and requires a visible Linux browser session for login. Native Windows collection is not provided.

`media-missher --help` lists `doctor`, `install-skill`, `setup`, `collect` and `runs`. Setup and collection use the exact same implementation as the separate Harness/Cordis Bundle, with user-private defaults independent of DSH_HOME. Neither installing nor checking a blank device launches Chrome.

GPT-6 Astra and other models use this entry through their host's shell and installed Skill. Keep the user's model and reasoning settings; this package does not call a model API. Verify the CLI/runtime versions and Skill activation in the intended task. Collection saves private evidence; export follows the user's selected targets, record kinds, fields and format. Chrome CDP is the only active browser backend. Read-only capability discovery does not establish browser readiness.

Copyright (c) 2026 Missher. All rights reserved. Original software may not be modified, redistributed or used for derivative work without permission, subject to LICENSE and applicable law. Third-party notices remain in effect. This package is a private local candidate; public hosting has not been deployed.
