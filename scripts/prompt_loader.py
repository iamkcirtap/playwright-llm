"""Helpers for loading prompt templates and injecting variables.

The generator keeps prompts in text files so they are easy to read and update
without changing Python logic.
"""

from pathlib import Path


PROMPT_DIR = Path("prompts")
OPTIONAL_PROMPT_DIR = PROMPT_DIR / "optional"

def get_prompt_path(prompt_name: str) -> Path:
    """Find a prompt file in the main prompts folder or optional subfolder."""
    candidate_paths = [
        PROMPT_DIR / f"{prompt_name}.txt",
        OPTIONAL_PROMPT_DIR / f"{prompt_name}.txt",
    ]
    for path in candidate_paths:
        if path.is_file():
            return path
    raise FileNotFoundError(f"Prompt file '{prompt_name}.txt' not found.")


def load_prompt(prompt_name: str) -> str:
    """Read a prompt file and return it as a trimmed string."""
    prompt_path = get_prompt_path(prompt_name)
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read().strip()
    

def inject_variables(prompt: str, variables: dict) -> str:
    """Replace template markers like {{ENDPOINT}} with real values."""
    for key, value in variables.items():
        prompt = prompt.replace(f"{{{{{key}}}}}", value)
    return prompt
    

def build_prompt(base: str, specific: str, variables: dict) -> str:
    """Combine the base prompt, focused prompt, and template variables."""
    if "{{SPECIFIC_PROMPT}}" in base:
        prompt = base.replace("{{SPECIFIC_PROMPT}}", specific)
    else:
        prompt = f"{base}\n\n{specific}"
    return inject_variables(prompt, variables)
