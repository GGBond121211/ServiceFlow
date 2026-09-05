from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True, slots=True)
class ContextSection:
    name: str
    content: str
    priority: int
    required: bool = False


@dataclass(frozen=True, slots=True)
class ContextBudget:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class ContextBuild:
    text: str
    kept_sections: tuple[str, ...]
    dropped_sections: tuple[str, ...]
    estimated_input_tokens: int


class ContextBudgetExceeded(ValueError):
    pass


def estimate_tokens(text: str) -> int:
    return max(1, ceil(len(text) / 4)) if text else 0


def build_context(
    sections: tuple[ContextSection, ...],
    *,
    budget: ContextBudget,
) -> ContextBuild:
    required = [section for section in sections if section.required]
    optional = sorted(
        (section for section in sections if not section.required),
        key=lambda section: (-section.priority, section.name),
    )
    selected: list[ContextSection] = []
    used = 0
    for section in required:
        cost = estimate_tokens(section.content)
        if used + cost > budget.input_tokens:
            raise ContextBudgetExceeded(f"必需上下文区块 {section.name} 超出预算")
        selected.append(section)
        used += cost
    for section in optional:
        cost = estimate_tokens(section.content)
        if used + cost <= budget.input_tokens:
            selected.append(section)
            used += cost
    selected.sort(key=lambda section: sections.index(section))
    kept = tuple(section.name for section in selected)
    dropped = tuple(section.name for section in sections if section.name not in kept)
    text = "\n\n".join(f"[{section.name}]\n{section.content}" for section in selected)
    return ContextBuild(
        text=text,
        kept_sections=kept,
        dropped_sections=dropped,
        estimated_input_tokens=used,
    )
