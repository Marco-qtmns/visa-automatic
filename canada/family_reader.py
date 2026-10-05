"""Verified family header aliases; source answers remain uninterpreted."""
from .family_schema import SCHEMA

from .models import FamilyData, FamilyMember, RelationshipData



def read_family(row):
    from .source_readers import _column_indexes, _column_value

    consumed = set()

    def value(labels, start=0, end=None):
        indexes = [i for i in _column_indexes(row, *labels)
                   if start <= i < (len(row.headers) if end is None else end)]
        if len(indexes) > 1:
            raise ValueError("Ambiguous Canada family field: " + labels[0])
        consumed.update(indexes)
        return _column_value(row, indexes[0]) if indexes else ""

    relationships = RelationshipData(**{
        field: value(labels) for field, labels in SCHEMA["relationships"].items()
    })
    family = FamilyData(has_children_answer=value(["Você possui filhos?"]))
    # Keep both source slots, even if one is empty. Never infer parental role.
    for block, aliases in enumerate(SCHEMA["parents"], 1):
        anchors = _column_indexes(row, *aliases["full_name"])
        if not anchors:
            continue
        if len(anchors) != 1:
            raise ValueError("Ambiguous Canada parent block")
        start = anchors[0]
        stops = _column_indexes(row, "Você possui filhos?", *SCHEMA["parents"][1]["full_name"])
        end = min((i for i in stops if i > start), default=len(row.headers))
        role = "parent_or_guardian" if "responsável" in row.headers[start].lower() else "parent"
        family.parents.append(FamilyMember(
            source_block_index=block, source_role=role,
            **{field: value(labels, start, end) for field, labels in aliases.items()}
        ))
    anchors = _column_indexes(row, *SCHEMA["children"]["relationship"])
    for block, start in enumerate(anchors, 1):
        end = anchors[block] if block < len(anchors) else len(row.headers)
        family.children.append(FamilyMember(
            source_block_index=block, source_role="child",
            **{field: value(labels, start, end) for field, labels in SCHEMA["children"].items()},
            has_more_children_answer=value(["Você possui outros filhos?"], start, end)
        ))
    # Missing anchors must not silently discard recognized member columns.
    aliases = [*SCHEMA["parents"], SCHEMA["children"]]
    recognized = {i for group in aliases for labels in group.values()
                  for i in _column_indexes(row, *labels)}
    if recognized - consumed:
        raise ValueError("Ambiguous Canada family layout: missing or misplaced member block anchor")
    return relationships, family


def family_review_sections(case):
    yield "Relationships (source answers)", case.relationships
    yield "Family — children declared: " + (case.family.has_children_answer or "unknown"), None
    for group in (case.family.parents, case.family.children):
        for member in group:
            yield f"{member.source_role} — source block {member.source_block_index}", member
