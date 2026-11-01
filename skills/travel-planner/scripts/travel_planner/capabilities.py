"""Replaceable, read-only data boundary. No provider SDK or implicit network calls."""

from dataclasses import dataclass, field
from typing import Protocol

from .model import PlannerError, now

CAPABILITIES = ("maps", "rail", "hotels", "rental", "energy", "attractions", "weather")


@dataclass(frozen=True)
class CapabilityRequest:
    capability: str
    conditions: dict


@dataclass
class CapabilityResult:
    capability: str
    status: str  # available / partial / unavailable
    data_mode: str  # mock / user_provided / live
    queried_at: str
    conditions: dict
    records: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    failure_reason: str | None = None
    limitations: list = field(default_factory=list)


class Adapter(Protocol):
    def query(self, request: CapabilityRequest) -> CapabilityResult: ...


class ProvidedDataAdapter:
    """A supplied response is evidence to examine, not an automatic live verification."""
    def __init__(self, response=None, mock=False):
        self.response, self.mock = response, mock

    def query(self, request):
        if request.capability not in CAPABILITIES:
            raise PlannerError("capability", "不支持的能力类型")
        if self.response is None:
            return CapabilityResult(request.capability, "unavailable", "mock" if self.mock else "user_provided",
                                    now(), request.conditions, failure_reason="没有提供查询结果",
                                    limitations=["继续不依赖该信息的规划；本接口未执行实时查询"])
        response = self.response
        if not isinstance(response, dict) or not isinstance(response.get("records"), list) or not isinstance(response.get("sources"), list):
            raise PlannerError("capability_response", "响应必须包含 records 和 sources 数组")
        if response.get("conditions") != request.conditions:
            return CapabilityResult(request.capability, "unavailable", "mock" if self.mock else "user_provided",
                                    now(), request.conditions, failure_reason="数据适用条件与请求不匹配")
        status = "available" if response["records"] and response["sources"] else "partial"
        return CapabilityResult(request.capability, status, "mock" if self.mock else "user_provided",
                                now(), request.conditions, response["records"], response["sources"],
                                limitations=["模拟数据，不能证明真实查询能力" if self.mock else
                                             "用户提供的资料；来源、适用日期及完整性仍需逐项核验"])
