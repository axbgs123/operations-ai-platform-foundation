import hashlib
import json
from enum import Enum
from types import UnionType
from typing import Literal, get_args, get_origin
from uuid import UUID

from pydantic import BaseModel

from app.modules.models.capabilities import (
    AdapterStatus,
    Capability,
    IncompatibleModelError,
    ModelRequest,
    StructuredOutput,
)


class MockProvider:
    status = AdapterStatus.VERIFIED

    def __init__(
        self,
        *,
        capabilities: frozenset[Capability] = frozenset(Capability),
    ) -> None:
        self.capabilities = capabilities

    async def generate_structured(
        self,
        request: ModelRequest[StructuredOutput],
    ) -> StructuredOutput:
        if request.capability not in self.capabilities:
            raise IncompatibleModelError(
                f"mock provider lacks capability: {request.capability.value}"
            )
        fingerprint = self._fingerprint(request)
        payload = {
            field_name: self._value_for(
                field.annotation,
                field_name,
                fingerprint,
                field.metadata,
            )
            for field_name, field in request.response_model.model_fields.items()
        }
        return request.response_model.model_validate(payload)

    @staticmethod
    def _fingerprint(request: ModelRequest[StructuredOutput]) -> str:
        canonical = json.dumps(
            {
                "capability": request.capability.value,
                "prompt": request.prompt,
                "inputs": request.inputs,
                "response_model": request.response_model.__name__,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    @classmethod
    def _value_for(
        cls,
        annotation: object,
        field_name: str,
        fingerprint: str,
        metadata: list[object] | None = None,
    ) -> object:
        if field_name == "fingerprint":
            return fingerprint
        if annotation is str:
            return f"mock-{field_name}-{fingerprint[:12]}"
        if annotation is float:
            return cls._bounded_number(
                cls._float_value(fingerprint, 0), metadata or [], integer=False
            )
        if annotation is int:
            return cls._bounded_number(
                int(fingerprint[:8], 16), metadata or [], integer=True
            )
        if annotation is bool:
            return int(fingerprint[0], 16) % 2 == 0
        if annotation is UUID:
            return UUID(hex=fingerprint[:32])
        if isinstance(annotation, type) and issubclass(annotation, Enum):
            return next(iter(annotation))
        origin = get_origin(annotation)
        arguments = get_args(annotation)
        if origin is Literal and arguments:
            return arguments[0]
        if origin is list and arguments:
            return [
                cls._float_value(fingerprint, index)
                if arguments[0] is float
                else cls._value_for(
                    arguments[0],
                    f"{field_name}_{index}",
                    fingerprint,
                )
                for index in range(4)
            ]
        if origin is dict and len(arguments) == 2:
            key = cls._value_for(
                arguments[0], f"{field_name}_key", fingerprint
            )
            value = cls._value_for(
                arguments[1], f"{field_name}_value", fingerprint
            )
            return {key: value}
        if origin in (UnionType, type(None)) or type(None) in arguments:
            non_none = next(
                (argument for argument in arguments if argument is not type(None)),
                str,
            )
            return cls._value_for(non_none, field_name, fingerprint)
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return {
                name: cls._value_for(
                    field.annotation, name, fingerprint, field.metadata
                )
                for name, field in annotation.model_fields.items()
            }
        raise TypeError(
            f"mock provider cannot generate field {field_name!r} with {annotation!r}"
        )

    @staticmethod
    def _float_value(fingerprint: str, index: int) -> float:
        offset = (index * 2) % (len(fingerprint) - 2)
        raw = int(fingerprint[offset : offset + 2], 16)
        return round((raw / 127.5) - 1, 6)

    @staticmethod
    def _bounded_number(
        value: float | int,
        metadata: list[object],
        *,
        integer: bool,
    ) -> float | int:
        lower: float | None = None
        upper: float | None = None
        for constraint in metadata:
            ge = getattr(constraint, "ge", None)
            gt = getattr(constraint, "gt", None)
            le = getattr(constraint, "le", None)
            lt = getattr(constraint, "lt", None)
            if ge is not None:
                lower = float(ge)
            if gt is not None:
                lower = float(gt) + (1 if integer else 1e-6)
            if le is not None:
                upper = float(le)
            if lt is not None:
                upper = float(lt) - (1 if integer else 1e-6)
        numeric = float(value)
        if lower is not None:
            numeric = max(numeric, lower)
        if upper is not None:
            numeric = min(numeric, upper)
        return int(numeric) if integer else numeric
