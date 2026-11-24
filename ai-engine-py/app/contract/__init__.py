"""契约加载与运行时校验：以 docs/contracts 下的 JSON Schema 为唯一事实来源。"""

from app.contract.loader import (
    CONTRACT_VERSION,
    ContractViolation,
    contract_version,
    schema_path,
    validate_instance,
)

__all__ = [
    "CONTRACT_VERSION",
    "ContractViolation",
    "contract_version",
    "schema_path",
    "validate_instance",
]
