import yaml

def load_prompts(filepath="prompts.yaml"):
    """Lädt die YAML-Datei und gibt ein Dictionary zurück."""
    with open(filepath, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)

def get_prompt_labels(prompts_dict):
    """Gibt ein Dictionary {label: id} zurück. Perfekt für das Streamlit Dropdown!"""
    return {data["label"]: prompt_id for prompt_id, data in prompts_dict.items()}

def get_system_instruction(prompts_data, profile_key='default'):
    """Kombiniert den Basis-Prompt mit den Serien-spezifischen Regeln."""
    base_prompt = prompts_data.get('default', {}).get('system_prompt', '')

    if profile_key and profile_key != 'default' and profile_key in prompts_data:
        series_prompt = prompts_data[profile_key].get('system_prompt', '')
        if series_prompt:
            return f"{base_prompt}\n\nSERIEN-SPEZIFISCHE REGELN:\n{series_prompt}"

    return base_prompt

def get_edtech_instruction(prompts_data, profile_key):
    """Holt den spezifischen EdTech-Vokabel-Prompt für das gewählte Serienprofil."""
    if profile_key in prompts_data:
        return prompts_data[profile_key].get("edtech_prompt", prompts_data.get("default", {}).get("edtech_prompt", ""))
    return prompts_data.get("default", {}).get("edtech_prompt", "")