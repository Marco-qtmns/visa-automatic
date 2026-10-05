from __future__ import annotations

from australia.workflow import AustraliaWorkflow
from canada.workflow import CanadaWorkflow


WORKFLOWS = {
    "australia": AustraliaWorkflow(),
    "canada": CanadaWorkflow(),
}


def get_workflow(name: str):
    try:
        return WORKFLOWS[name]
    except KeyError as exc:
        raise ValueError(f"Unsupported visa destination: {name}") from exc
