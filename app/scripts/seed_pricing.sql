insert into provider_pricing (provider, model, input_cost_per_1k_tokens, output_cost_per_1k_tokens)
values
  ('nvidia','moonshotai/kimi-k2.5',0,0),
  ('nvidia','qwen/qwen3.5-397b-a17b',0,0),
  ('nvidia','openai/gpt-oss-120b',0,0),
  ('nvidia','z-ai/glm4.7',0,0),
  ('nvidia','google/gemma-3n-e4b-it',0,0),
  ('openai','gpt-4o',0,0)
on conflict (provider, model) do update
set input_cost_per_1k_tokens=excluded.input_cost_per_1k_tokens,
    output_cost_per_1k_tokens=excluded.output_cost_per_1k_tokens;
