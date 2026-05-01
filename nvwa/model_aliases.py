import os


MODEL_ALIASES = {
    "gpt_5_4": "gpt-5.4",
}

READABLE_MODEL_NAMES = {model_id: alias for alias, model_id in MODEL_ALIASES.items()}


def resolve_model_alias(model: str) -> str:
    normalized = str(model).strip().lower()
    return MODEL_ALIASES.get(normalized, model)


def readable_model_name(model: str) -> str:
    return READABLE_MODEL_NAMES.get(model, model)


def readable_model_dirname(model: str) -> str:
    readable_name = readable_model_name(model)
    return readable_name.replace(os.sep, "_")
