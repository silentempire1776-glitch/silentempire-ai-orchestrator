MODEL_REGISTRY = {
    "gpt-4o": {
        "provider": "openai",
        "timeout": 30,
        "cost_input_per_1k": 0.01,
        "cost_output_per_1k": 0.03
    },
    "kimi-large": {
        "provider": "nvidia",
        "timeout": 45,
        "cost_input_per_1k": 0.002,
        "cost_output_per_1k": 0.006
    }
}
