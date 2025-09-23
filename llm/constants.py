# Add a dictionary to map LLM providers to their default base URLs
LLM_BASE_URLS = {
    "Deepseek": "https://api.deepseek.com/v1",
    "ChatGPT": "https://api.openai.com/v1",
    "Gemini": "https://generativelanguage.googleapis.com/v1beta",
    "Claude": "https://api.anthropic.com/v1",
    "豆包": "https://ark.cn-beijing.volces.com/api/v3",
    "通义千问": "https://dashscope.aliyuncs.com/api/v1"
}

# Add a dictionary to map LLM providers to their available models
LLM_MODELS = {
    "Deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "ChatGPT": ["gpt-4o", "gpt-4", "gpt-3.5-turbo"],
    "Gemini": ["gemini-pro"],
    "Claude": ["claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307"],
    "豆包": ["doubao-seed-1.6", "doubao-seed-1.6-flash", "doubao-seed-1.6-thinking"],
    "通义千问": ["qwen-max", "qwen-plus"]
}

LLM_ADAPTER = {
    "Deepseek": "openai",
    "ChatGPT": "openai",
    "Gemini": "genai",
    "Claude": "anthropic",
    "豆包": "openai",
    "通义千问": "openai"
}