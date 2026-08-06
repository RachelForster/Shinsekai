from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Callable, Mapping
from urllib.parse import unquote

from frontend_bridge_core.routes.uploads import UploadedFiles

if TYPE_CHECKING:
    from application.runtime.state import BridgeState


class BodyKind(str, Enum):
    NONE = "none"
    JSON = "json"
    MULTIPART = "multipart"


@dataclass(frozen=True, slots=True)
class JsonResponse:
    data: Any
    status: HTTPStatus = HTTPStatus.OK


@dataclass(frozen=True, slots=True)
class TaskResponse:
    kind: str
    title: str
    message: str
    worker: Callable[[str], Any]
    task_updates: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ApiRequest:
    state: BridgeState
    method: str
    path: str
    query: Mapping[str, list[str]]
    params: Mapping[str, str]
    body: dict[str, Any]
    uploads: UploadedFiles | None = None


RouteResponse = JsonResponse | TaskResponse
RouteHandler = Callable[[ApiRequest], RouteResponse]

_PARAMETER_SEGMENT = re.compile(r"^\{([A-Za-z_][A-Za-z0-9_]*)\}$")
_SUPPORTED_METHODS = frozenset({"DELETE", "GET", "HEAD", "POST", "PUT"})


def _compile_pattern(pattern: str) -> re.Pattern[str]:
    if not pattern.startswith("/"):
        raise ValueError(f"route pattern must start with '/': {pattern}")

    parameter_names: set[str] = set()
    compiled_segments: list[str] = []
    for segment in pattern.split("/")[1:]:
        parameter = _PARAMETER_SEGMENT.fullmatch(segment)
        if parameter is None:
            compiled_segments.append(re.escape(segment))
            continue

        name = parameter.group(1)
        if name in parameter_names:
            raise ValueError(f"duplicate route parameter {name!r}: {pattern}")
        parameter_names.add(name)
        compiled_segments.append(f"(?P<{name}>[^/]+)")

    return re.compile("^/" + "/".join(compiled_segments) + "$")


def _pattern_shape(pattern: str) -> tuple[str, ...]:
    return tuple(
        "{}" if _PARAMETER_SEGMENT.fullmatch(segment) else segment
        for segment in pattern.split("/")[1:]
    )


@dataclass(frozen=True, slots=True)
class Route:
    methods: frozenset[str]
    pattern: str
    handler: RouteHandler
    body_kind: BodyKind = BodyKind.JSON
    name: str = ""
    _compiled_pattern: re.Pattern[str] = field(init=False, repr=False, compare=False)
    _shape: tuple[str, ...] = field(init=False, repr=False, compare=False)
    _specificity: int = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        methods = frozenset(str(method).upper() for method in self.methods)
        if not methods:
            raise ValueError(f"route must accept at least one method: {self.pattern}")
        unsupported = methods - _SUPPORTED_METHODS
        if unsupported:
            raise ValueError(
                f"unsupported route methods for {self.pattern}: {sorted(unsupported)}"
            )
        object.__setattr__(self, "methods", methods)
        object.__setattr__(self, "_compiled_pattern", _compile_pattern(self.pattern))
        shape = _pattern_shape(self.pattern)
        object.__setattr__(self, "_shape", shape)
        object.__setattr__(
            self,
            "_specificity",
            sum(segment != "{}" for segment in shape),
        )

    def match_path(self, path: str) -> Mapping[str, str] | None:
        matched = self._compiled_pattern.fullmatch(path)
        if matched is None:
            return None
        return {name: unquote(value) for name, value in matched.groupdict().items()}


@dataclass(frozen=True, slots=True)
class RouteMatch:
    route: Route
    params: Mapping[str, str]


class Router:
    def __init__(self, routes: tuple[Route, ...] | list[Route]) -> None:
        self._routes = tuple(
            sorted(routes, key=lambda route: route._specificity, reverse=True)
        )
        seen: dict[tuple[str, tuple[str, ...]], tuple[str, str]] = {}
        for route in self._routes:
            for method in route.methods:
                key = (method, route._shape)
                if key in seen:
                    first_pattern, registered_name = seen[key]
                    first_name = registered_name or first_pattern
                    second_name = route.name or route.pattern
                    raise ValueError(
                        f"duplicate route shape {method} {route.pattern}: "
                        f"{first_name!r} and {second_name!r}"
                    )
                seen[key] = (route.pattern, route.name)

    @property
    def routes(self) -> tuple[Route, ...]:
        return self._routes

    def match(self, method: str, path: str) -> RouteMatch | None:
        normalized_method = str(method).upper()
        for route in self._routes:
            if normalized_method not in route.methods:
                continue
            params = route.match_path(path)
            if params is not None:
                return RouteMatch(route=route, params=params)
        return None
