"""12 majors + алиасы для матчинга в заголовке/тексте."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Company:
    id: str
    name: str
    patterns: tuple[str, ...]
    strong: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()


COMPANIES: list[Company] = [
    Company("exxonmobil", "ExxonMobil", (r"\bexxon\s*mobil\b", r"\bexxonmobil\b", r"\bexxon\b")),
    Company(
        "shell",
        "Shell",
        (r"\bshell\b",),
        strong=(r"\bshell plc\b", r"\bshell oil\b", r"\broyal dutch shell\b"),
        exclude=(
            r"shell company",
            r"shell companies",
            r"powershell",
            r"ghost in the shell",
            r"shell script",
            r"shell out",
            r"java4shell",
            r"ruby2shell",
            r"nginx2root",
        ),
    ),
    Company(
        "bp",
        "BP",
        (r"(?<![a-z])bp(?![a-z])", r"\bbp'?s\b"),
        strong=(r"\bbp plc\b", r"\bbritish petroleum\b"),
    ),
    Company(
        "totalenergies",
        "TotalEnergies",
        (r"\btotalenergies\b", r"\btotal energies\b"),
    ),
    Company("chevron", "Chevron", (r"\bchevron\b",)),
    Company("equinor", "Equinor", (r"\bequinor\b", r"\bstatoil\b")),
    Company(
        "eni",
        "Eni",
        (r"(?<![a-z])eni(?![a-z])",),
        strong=(r"\beni spa\b", r"\beni s\.p\.a\b"),
        exclude=(r"\beni\s+rama\b",),
    ),
    Company(
        "conocophillips",
        "ConocoPhillips",
        (r"\bconocophillips\b", r"\bconoco\s*phillips\b", r"(?<![a-z])cop(?![a-z0-9])"),
        strong=(r"\bconocophillips\b", r"\bconoco\s*phillips\b"),
        exclude=(r"\bcop\d{2}\b", r"\bcop26\b", r"\bcop27\b", r"\bcop28\b", r"\bcop29\b", r"\bcop30\b", r"\bcop31\b"),
    ),
    Company("petrobras", "Petrobras", (r"\bpetrobras\b",)),
    Company(
        "occidental",
        "Occidental (Oxy)",
        (r"\boccidental petroleum\b", r"\boccidental\b", r"(?<![a-z])oxy(?![a-z])"),
        strong=(r"\boccidental petroleum\b",),
        exclude=(r"oxycontin", r"\boxygen\b", r"oxy-?acetylene"),
    ),
    Company("aramco", "Saudi Aramco", (r"\bsaudi aramco\b", r"\baramco\b")),
    Company("adnoc", "ADNOC", (r"\badnoc\b", r"\babu dhabi national oil\b")),
]

NEED_CONTEXT = {"bp", "shell", "eni", "occidental", "conocophillips"}
OIL_CONTEXT = re.compile(
    r"\b(oil|gas|lng|upstream|downstream|offshore|refiner(?:y|ies)|petroleum|"
    r"drilling|exploration|energy|hydrocarbon|barrel|permian|north sea|o&g|"
    r"subsurface|deepwater|rig|wellhead|reservoir|production|midstream)\b",
    re.I,
)


def match_companies(text: str) -> list[Company]:
    blob = text or ""
    hit: list[Company] = []
    for co in COMPANIES:
        if not any(re.search(p, blob, re.I) for p in co.patterns):
            continue
        has_strong = any(re.search(p, blob, re.I) for p in co.strong) if co.strong else False
        if co.exclude and any(re.search(ex, blob, re.I) for ex in co.exclude) and not has_strong:
            continue
        if co.id in NEED_CONTEXT and not has_strong and not OIL_CONTEXT.search(blob):
            continue
        hit.append(co)
    return hit
