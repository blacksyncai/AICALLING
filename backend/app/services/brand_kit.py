"""A finite set of safe design tokens, not arbitrary customer CSS or remote fonts."""

import re

from fastapi import HTTPException

DEFAULT_KIT = {
    "primary": "#dc4a1e",
    "accent": "#f59e0b",
    "sidebar": "#181411",
    "surface": "#f8f6f3",
    "text": "#211b18",
    "font": "geist",
    "button_shape": "rounded",
}


def luminance(color):
    values = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    channels = [
        v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values
    ]
    return sum(
        v * weight for v, weight in zip(channels, (0.2126, 0.7152, 0.0722), strict=True)
    )


def validate_kit(raw):
    if not isinstance(raw, dict) or set(raw) - set(DEFAULT_KIT):
        raise HTTPException(422, "Use only the supported brand-kit settings.")
    kit = {**DEFAULT_KIT, **raw}
    for key in ("primary", "accent", "sidebar", "surface", "text"):
        if not isinstance(kit[key], str) or not re.fullmatch(
            r"#[0-9a-fA-F]{6}", kit[key]
        ):
            raise HTTPException(
                422, f"{key}: enter a six-digit hex color such as #2458a6."
            )
        kit[key] = kit[key].lower()
    if kit["font"] not in ("geist", "grotesk", "system") or kit["button_shape"] not in (
        "rounded",
        "pill",
        "square",
    ):
        raise HTTPException(422, "Choose one of the supported fonts and button shapes.")
    light, dark = sorted(
        (luminance(kit["surface"]), luminance(kit["text"])), reverse=True
    )
    if (light + 0.05) / (dark + 0.05) < 4.5:
        raise HTTPException(
            422,
            "Workspace text needs at least 4.5:1 contrast against the workspace background.",
        )
    if luminance(kit["surface"]) < 0.75:
        raise HTTPException(
            422,
            "Choose a light workspace background for the app's light-theme controls.",
        )
    if 1.05 / (luminance(kit["sidebar"]) + 0.05) < 4.5:
        raise HTTPException(
            422,
            "Choose a dark sidebar color with at least 4.5:1 contrast against white text.",
        )
    return kit
