"""
Downloads allenai/OLMo-2-1124-7B-Instruct for WCAG report narrative generation.
Run during Modal image build to pre-cache model weights.
"""
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

print("Downloading OLMo2 tokenizer...")
AutoTokenizer.from_pretrained("allenai/OLMo-2-1124-7B-Instruct")
print("Tokenizer cached.")

print("Downloading OLMo2-7B-Instruct weights (this takes a while)...")
AutoModelForCausalLM.from_pretrained(
    "allenai/OLMo-2-1124-7B-Instruct",
    torch_dtype=torch.bfloat16,
    device_map="auto",
)
print("OLMo2 model cached. Ready for deployment.")
