CLAUDE, CODEX, OPENCODE = "claude", "codex", "opencode"

CAPABILITIES = {
    CLAUDE: {"label": "Claude CLI", "models": ["sonnet", "opus", "haiku"],
             "efforts": ["low", "medium", "high", "max"],
             "accepts_custom_model": True},
    CODEX: {"label": "Codex CLI", "models": [],
            "efforts": ["low", "medium", "high", "xhigh", "max", "ultra"],
            "accepts_custom_model": True},
    OPENCODE: {"label": "OpenCode CLI", "models": [], "efforts": [],
               "accepts_custom_model": True},
}


def describe(config):
    out = config.as_dict()
    out.update(CAPABILITIES.get(config.kind, {}))
    return out
