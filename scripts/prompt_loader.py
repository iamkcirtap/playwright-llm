from pathlib import Path
import os


PROMPT_DIR = Path("prompts")

# main folder is "prompts" but also consider looking within subfolders for better organization
def get_prompt_path(prompt_name: str) -> Path:
    # search for the prompt file in the prompts directory and its subdirectories
    print(f"Searching for prompt file '{prompt_name}.txt' in '{PROMPT_DIR}' and its subdirectories...")
    for root, _, files in os.walk(PROMPT_DIR):
        for file in files:
            if file == f"{prompt_name}.txt":
                return Path(root) / file
            print(f"Found prompt file '{file}' at '{root}'.")
    raise FileNotFoundError(f"Prompt file '{prompt_name}.txt' not found in '{PROMPT_DIR}' or its subdirectories.")


# this function will load the prompt file and return its content as a string, 
# it will also print the path of the loaded prompt file for debugging purposes
def load_prompt(prompt_name: str) -> str:
    prompt_path = get_prompt_path(prompt_name)
    print(f"Loading prompt '{prompt_name}' from '{prompt_path}'.")
    if not prompt_path.is_file():
        raise FileNotFoundError(f"Prompt file '{prompt_path}' does not exist.")
    with open(prompt_path, "r") as f:
        return f.read().strip()
    

# this function will inject the variables into the prompt template, 
# it will replace the placeholders in the prompt with the actual values from the variables dictionary
def inject_variables(prompt: str, variables: dict) -> str:
    print(f"Injecting variables into prompt: {variables}")
    for key, value in variables.items():
        prompt = prompt.replace(f"{{{{{key}}}}}", value)
    return prompt
    

# this function will build the full prompt by combining the base prompt, the specific prompt, and the variables,
# it will first replace the {{SPECIFIC_PROMPT}} placeholder in the base prompt with the specific prompt, 
# and then inject the variables into the resulting prompt
def build_prompt(base: str, specific: str, variables: dict) -> str:
    print(f"Building prompt with base: {base}, specific: {specific}, variables: {variables}")
    if "{{SPECIFIC_PROMPT}}" in base:
        prompt = base.replace("{{SPECIFIC_PROMPT}}", specific)
    else:
        prompt = f"{base}\n\n{specific}"
    return inject_variables(prompt, variables)
