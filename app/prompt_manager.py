import yaml

def load_prompts(filepath="prompts.yaml"):
    """Lädt die YAML-Datei und gibt ein Dictionary zurück."""
    with open(filepath, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)

def get_prompt_labels(prompts_dict):
    """Gibt ein Dictionary {label: id} zurück. Perfekt für das Streamlit Dropdown!"""
    return {data["label"]: prompt_id for prompt_id, data in prompts_dict.items()}

def get_system_instruction(prompts_dict, prompt_id):
    """Holt den reinen System-Prompt basierend auf der ausgewählten ID."""
    if prompt_id in prompts_dict:
        return prompts_dict[prompt_id]["system_prompt"]
    # Fallback auf Default, falls eine ungültige ID übergeben wird
    return prompts_dict.get("default", {}).get("system_prompt", "")

def get_edtech_instruction(prompts_data, profile_key):
    """Holt den spezifischen EdTech-Vokabel-Prompt für das gewählte Serienprofil."""
    if profile_key in prompts_data:
        return prompts_data[profile_key].get("edtech_prompt", prompts_data.get("default", {}).get("edtech_prompt", ""))
    return prompts_data.get("default", {}).get("edtech_prompt", "")