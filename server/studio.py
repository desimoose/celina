"""Studio - turn a source into content.

Takes text the user has collected (a paper they read, a saved brief) and asks
the model to rewrite it into a specific format: a TikTok script, a two-host
podcast segment, a LinkedIn carousel. Grounded strictly in the source, so the
output stays honest to what was actually researched.

Every format routes through the same gateway (BYOK or local), so it costs
nothing extra to run and works with whatever model is selected.
"""

FORMATS = {
    "tiktok": {
        "label": "TikTok script",
        "system": (
            "You write a spoken 45-60 second TikTok monologue (a 'yap'). "
            "First person, one strong hook in the opening line, short spoken "
            "sentences, no scene directions. Ground it strictly in the source "
            "below; do not invent facts. Land on one clear takeaway. After the "
            "script, add a final line with 4-6 relevant lowercase hashtags."
        ),
    },
    "podcast": {
        "label": "Podcast episode",
        "system": (
            "You write a 3-4 minute two-host podcast segment. Hosts are Ada and "
            "Reese: Ada is curious and asks, Reese explains clearly. Natural "
            "back-and-forth, label each turn 'Ada:' / 'Reese:'. Open with a "
            "one-line cold open, cite specifics from the source, close on a "
            "takeaway. Ground strictly in the source below; do not invent facts."
        ),
    },
    "linkedin": {
        "label": "LinkedIn slideshow",
        "system": (
            "You write a LinkedIn carousel of 6-8 slides. Format each as "
            "'Slide N:' with a bold one-line title then 1-2 short body lines. "
            "Slide 1 is the hook, the last slide is the takeaway plus a soft "
            "question to the reader. Professional but plain-spoken, no "
            "buzzwords. Ground strictly in the source below; do not invent facts."
        ),
    },
}


# Keep the content to the same craft bar as the interface: no hype filler.
_PLAIN = (
    " Use plain, concrete language. Do not use hype words (revolutionize, "
    "game-changing, unlock, seamless, leverage, supercharge, elevate)."
)


def generate(gateway, provider, fmt, source):
    spec = FORMATS.get(fmt)
    if not spec:
        raise ValueError(f"unknown format '{fmt}'")
    source = (source or "").strip()
    if not source:
        raise ValueError("no source to work from - open a paper or a brief first")

    system = spec["system"] + _PLAIN + "\n\nSource:\n" + source[:40000]
    return gateway.chat(
        provider,
        [{"role": "user", "content": f"Write the {spec['label']} from the source."}],
        system=system,
        max_tokens=2000,
    )
