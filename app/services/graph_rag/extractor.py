"""Entity and relationship extraction from text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class EntityType(StrEnum):
    PERSON = "PERSON"
    ORG = "ORG"
    PRODUCT = "PRODUCT"
    CONCEPT = "CONCEPT"
    LOCATION = "LOCATION"


@dataclass
class Entity:
    name: str
    entity_type: EntityType
    mentions: int = 1
    source_chunks: list[int] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.entity_type.value}:{self.name.lower()}"


@dataclass
class Relationship:
    source: Entity
    target: Entity
    relation_type: str
    weight: float = 1.0
    source_chunks: list[int] = field(default_factory=list)


_PERSON_PATTERN = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b"
)
_ORG_PATTERN = re.compile(
    r"\b([A-Z][a-zA-Z]*(?:\s+(?:Inc|Corp|LLC|Ltd|Co|Group|Foundation|Institute|University|Association|Company|Technologies|Systems|Labs|Partners)\.?))\b"
)
_LOCATION_PATTERN = re.compile(
    r"\b(?:in|at|from|near)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b"
)
_PRODUCT_PATTERN = re.compile(
    r"\b([A-Z][a-zA-Z]*(?:[-][A-Z][a-zA-Z]*)*\s+(?:v\d|API|SDK|Platform|Engine|Framework|Model|System|Tool|Service))\b"
)


class EntityExtractor:
    """Extract entities and relationships from text (regex by default)."""

    def __init__(self, use_llm: bool = False) -> None:
        self._use_llm = use_llm

    def extract_entities(self, text: str, chunk_id: int = 0) -> list[Entity]:
        if self._use_llm:
            return self._extract_with_llm(text, chunk_id)
        return self._extract_with_regex(text, chunk_id)

    def extract_relationships(
        self, text: str, entities: list[Entity], chunk_id: int = 0
    ) -> list[Relationship]:
        sentences = re.split(r"[.!?]+", text)
        relationships: list[Relationship] = []
        seen: set[tuple[str, str]] = set()

        for sentence in sentences:
            sentence_lower = sentence.lower()
            present = [e for e in entities if e.name.lower() in sentence_lower]

            for i, e1 in enumerate(present):
                for e2 in present[i + 1 :]:
                    pair = (e1.id, e2.id)
                    if pair in seen:
                        continue
                    seen.add(pair)
                    relationships.append(
                        Relationship(
                            source=e1,
                            target=e2,
                            relation_type="co-occurs",
                            weight=1.0,
                            source_chunks=[chunk_id],
                        )
                    )

        return relationships

    def _extract_with_regex(self, text: str, chunk_id: int) -> list[Entity]:
        entity_map: dict[str, Entity] = {}

        patterns: list[tuple[re.Pattern[str], EntityType]] = [
            (_ORG_PATTERN, EntityType.ORG),
            (_PRODUCT_PATTERN, EntityType.PRODUCT),
            (_PERSON_PATTERN, EntityType.PERSON),
            (_LOCATION_PATTERN, EntityType.LOCATION),
        ]

        for pattern, etype in patterns:
            for match in pattern.finditer(text):
                name = match.group(1).strip()
                if len(name) < 2 or name in ("The", "This", "That", "These", "Those"):
                    continue
                key = f"{etype.value}:{name.lower()}"
                if key in entity_map:
                    entity_map[key].mentions += 1
                else:
                    entity_map[key] = Entity(
                        name=name,
                        entity_type=etype,
                        mentions=1,
                        source_chunks=[chunk_id],
                    )

        return list(entity_map.values())

    def _extract_with_llm(self, text: str, chunk_id: int) -> list[Entity]:
        import anthropic

        from app.config import settings

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        prompt = (
            "Extract all named entities from the following text. "
            "For each entity, output one line in the format: TYPE|NAME\n"
            "Valid types: PERSON, ORG, PRODUCT, CONCEPT, LOCATION\n"
            "Only output entity lines, nothing else.\n\n"
            f"Text:\n{text[:3000]}"
        )

        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            result_text = response.content[0].text
        except Exception:
            return self._extract_with_regex(text, chunk_id)

        entity_map: dict[str, Entity] = {}
        for line in result_text.strip().split("\n"):
            line = line.strip()
            if "|" not in line:
                continue
            parts = line.split("|", 1)
            if len(parts) != 2:
                continue
            etype_str, name = parts[0].strip(), parts[1].strip()
            try:
                etype = EntityType(etype_str)
            except ValueError:
                continue
            if len(name) < 2:
                continue
            key = f"{etype.value}:{name.lower()}"
            if key in entity_map:
                entity_map[key].mentions += 1
            else:
                entity_map[key] = Entity(
                    name=name,
                    entity_type=etype,
                    mentions=1,
                    source_chunks=[chunk_id],
                )

        return list(entity_map.values()) if entity_map else self._extract_with_regex(text, chunk_id)
